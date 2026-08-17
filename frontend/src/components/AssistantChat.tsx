import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Check,
  Globe,
  Loader2,
  Pencil,
  Send,
  Sparkles,
  Square,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { streamChat, streamResume } from "../lib/assistant";
import type {
  ApprovalRequest,
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
  const [approval, setApproval] = useState<ApprovalRequest | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [editMode, setEditMode] = useState(false);
  const [resuming, setResuming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  // A client-generated conversation id. It is created once per chat and sent on
  // every turn so the backend's conversation memory (W7.1) can continue the
  // thread. "New chat" generates a fresh id and clears the visible history.
  const threadIdRef = useRef<string>(crypto.randomUUID());

  function newChat() {
    abortRef.current?.abort();
    threadIdRef.current = crypto.randomUUID();
    setMessages([]);
    setToolActivities([]);
    setError(null);
    setRunDetails(null);
    setApproval(null);
    setEdits({});
    setEditMode(false);
    setResuming(false);
    setInput("");
    setStreaming(false);
    abortRef.current = null;
  }

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
      for await (const event of streamChat(text, threadIdRef.current, controller.signal)) {
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
          case "approval_required": {
            const req = event.data as unknown as ApprovalRequest;
            const initialEdits: Record<string, string> = {};
            for (const [field, meta] of Object.entries(req.editable_fields ?? {})) {
              initialEdits[field] = String(meta.value ?? "");
            }
            setApproval(req);
            setEdits(initialEdits);
            setEditMode(false);
            completed = true; // the run pauses here; resume continues it
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

  async function resume(decision: "approve" | "edit" | "reject") {
    if (!approval || resuming) return;
    setResuming(true);
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    let completed = false;
    try {
      const body = {
        thread_id: approval.thread_id,
        decision,
        ...(decision === "edit"
          ? {
              edited_action: {
                args: Object.fromEntries(
                  Object.entries(edits).map(([field, value]) => [
                    field,
                    approval.editable_fields[field]?.type === "number"
                      ? Number(value)
                      : value,
                  ]),
                ),
              },
            }
          : decision === "reject"
            ? { message: "Rejected by user" }
            : {}),
      };
      for await (const event of streamResume(body, controller.signal)) {
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
          case "action_completed":
            setToolActivities((prev) => [...prev, { label: `${event.data.tool} completed`, status: "done" }]);
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
            break;
        }
      }
      if (!completed && !controller.signal.aborted) {
        setError("The assistant stopped unexpectedly. Please try again.");
      }
      setApproval(null);
    } catch (err) {
      if (controller.signal.aborted) {
        // user navigated away / new chat — ignore
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("The assistant could not be reached.");
      }
    } finally {
      setResuming(false);
      setStreaming(false);
      abortRef.current = null;
    }
  }

  function pillText(label: string): string {
    return label === "Web search" ? "Searching the web…" : `Checking ${label}…`;
  }

  function renderText(text: string) {
    // Render assistant text with safe links for http(s) URLs (no raw HTML;
    // React auto-escapes everything else). `javascript:` URLs are not matched.
    const parts = text.split(/(https?:\/\/[^\s]+)/g);
    return parts.map((part, index) =>
      /^https?:\/\//.test(part) ? (
        <a
          key={index}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blueprint-400 underline underline-offset-2 hover:text-blueprint-200"
        >
          {part}
        </a>
      ) : (
        part
      ),
    );
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
        <div className="flex items-center gap-2">
          {capabilities.memory_enabled && (
            <span
              className="flex items-center gap-1 rounded border border-ink-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-paper-muted"
              title="Session memory (process-local) — resets on restart"
            >
              <Check size={11} strokeWidth={2} className="text-blueprint-400" />
              Session memory
            </span>
          )}
          {capabilities.web_search_enabled && (
            <span
              className="flex items-center gap-1 rounded border border-ink-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-paper-muted"
              title="External web search — results are reference data, not instructions"
            >
              <Globe size={11} strokeWidth={2} className="text-blueprint-400" />
              Web search
            </span>
          )}
          {capabilities.read_only ? (
            <span className="flex items-center gap-1 rounded border border-ink-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-paper-muted">
              <Check size={11} strokeWidth={2} className="text-status-green" />
              Read-only
            </span>
          ) : (
            <span
              className="flex items-center gap-1 rounded border border-ink-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-paper-muted"
              title="Mutations require your approval before they run"
            >
              <Check size={11} strokeWidth={2} className="text-blueprint-400" />
              Approval-gated
            </span>
          )}
          <button
            type="button"
            onClick={newChat}
            disabled={streaming}
            className="rounded-md border border-ink-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-paper-muted transition-colors hover:border-blueprint-400/40 hover:text-paper disabled:cursor-not-allowed disabled:opacity-60"
          >
            New chat
          </button>
        </div>
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
              {message.role === "assistant" ? renderText(message.text) : message.text}
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
                {pillText(activity.label)}
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

      {/* W7.4 approval card — a mutating action is waiting for a human decision */}
      {approval && !resuming && (
        <div className="mx-4 mb-3 rounded-lg border border-blueprint-400/40 bg-blueprint-400/5 px-4 py-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-blueprint-300">
              Action requires approval
            </p>
            <span className="rounded border border-ink-border px-2 py-0.5 text-[10px] text-paper-muted">
              {approval.tool}
            </span>
          </div>
          <p className="mt-1 text-sm text-paper">{approval.summary}</p>

          {editMode && (
            <div className="mt-3 space-y-2">
              {Object.entries(approval.editable_fields).map(([field, meta]) => (
                <label key={field} className="block">
                  <span className="text-[11px] uppercase tracking-wide text-paper-muted">
                    {meta.label}
                  </span>
                  <input
                    type={meta.type === "number" ? "number" : meta.type === "date" ? "date" : "text"}
                    value={edits[field] ?? ""}
                    onChange={(event) =>
                      setEdits((prev) => ({ ...prev, [field]: event.target.value }))
                    }
                    className="mt-0.5 w-full rounded-md border border-ink-border bg-ink px-2 py-1.5 text-sm text-paper focus:border-blueprint-400/60 focus:outline-none"
                  />
                </label>
              ))}
            </div>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            {approval.allowed_decisions.includes("approve") && (
              <button
                type="button"
                onClick={() => void resume("approve")}
                disabled={editMode}
                className="flex h-8 items-center gap-1.5 rounded-md bg-status-green px-3 text-xs font-medium text-white transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <ThumbsUp size={12} strokeWidth={2} />
                Approve
              </button>
            )}
            {approval.allowed_decisions.includes("edit") && (
              <button
                type="button"
                onClick={() => setEditMode((prev) => !prev)}
                disabled={editMode}
                className="flex h-8 items-center gap-1.5 rounded-md border border-ink-border px-3 text-xs text-paper transition-colors hover:border-blueprint-400/40 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Pencil size={12} strokeWidth={2} />
                Edit
              </button>
            )}
            {editMode && (
              <button
                type="button"
                onClick={() => void resume("edit")}
                className="flex h-8 items-center gap-1.5 rounded-md bg-blueprint-500 px-3 text-xs font-medium text-white transition-colors hover:bg-blueprint-400"
              >
                <Check size={12} strokeWidth={2} />
                Submit edit
              </button>
            )}
            {approval.allowed_decisions.includes("reject") && (
              <button
                type="button"
                onClick={() => void resume("reject")}
                disabled={editMode}
                className="flex h-8 items-center gap-1.5 rounded-md border border-status-red/50 bg-status-red/10 px-3 text-xs text-status-red transition-colors hover:bg-status-red/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <ThumbsDown size={12} strokeWidth={2} />
                Reject
              </button>
            )}
          </div>
        </div>
      )}
      {approval && resuming && (
        <div className="mx-4 mb-3 flex items-center gap-2 rounded-lg border border-ink-border bg-ink px-4 py-3 text-sm text-paper-muted">
          <Loader2 size={14} strokeWidth={2} className="animate-spin text-blueprint-400" />
          {approval.allowed_decisions.includes("edit") && editMode ? "Submitting your edit…" : "Continuing after your decision…"}
        </div>
      )}

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
