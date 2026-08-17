# W7.1 — Conversation Memory & Context Intelligence: Checkpoint Review

**Status:** COMPLETE. Checkpoint-specific record (the final Weekend-07 review is
created after W7.4).
**Date:** Aug 15, 2026.
**Baseline before W7.1:** AI-1 complete (390 backend / 56 AI tests), public
LangChain v1 runtime-context API, stateless Copilot.

---

## 1. Scope

Turn the stateless ICE Copilot into a real multi-turn conversational agent:
`InMemorySaver` + `thread_id`, multiple conversations, thread ownership /
cross-user isolation, runtime-context vs agent-state distinction,
`SummarizationMiddleware`, `ContextEditingMiddleware`, `ClearToolUsesEdit`, and
measured memory/context-growth behavior. W7.2/W7.3/W7.4 were NOT implemented.

## 2. Architecture

- **Memory:** `app/ai/memory.py` — one process-level `InMemorySaver` singleton;
  `memory_mode()` (`none|saver|summarize|context_edit`), `thread_key(user_id,
  external_thread) = "{user_id}::{external_thread}"`, `run_config(user_id,
  thread_id)` builds the namespaced `configurable.thread_id` (ephemeral random
  thread when none supplied and memory is on).
- **Agent:** `build_agent(role, model, memory_mode, summarization_model)` wires
  `create_agent(checkpointer=..., middleware=...)`:
  - `none` → no checkpointer (AI-1 stateless).
  - `saver` → InMemorySaver only.
  - `summarize` → saver + `SummarizationMiddleware(model, trigger=(kind,value),
    keep=("messages", N))`.
  - `context_edit` → saver + `ContextEditingMiddleware(edits=[ClearToolUsesEdit(
    trigger, keep, clear_tool_inputs=True)])`.
  - `context_schema=ActorContext` and invocation `context=actor` unchanged.
- **Invocation:** `stream_assistant`/`run_agent` accept `thread_id`; config
  carries the namespaced thread; the actor still flows through the public
  `context=` API into `ToolRuntime[ActorContext]`.

## 3. Checkpointer lifecycle

One module-level `InMemorySaver()` created at import and reused for the process
lifetime. It is NEVER instantiated per request (that would defeat memory).
Documented limitation: process-local — memory is lost on restart and is not
shared across backend workers. Persistent (Postgres/Redis) checkpoint storage is
explicitly deferred.

## 4. Thread namespacing

Internal key = `{actor.user_id}::{external_thread_id}`. A client-supplied UUID
(`thread_id`, UUID-validated) never becomes a global LangGraph key. The internal
key is never exposed to the model or the browser (SSE carries only the external
`thread_id`).

## 5. Security isolation

- Cross-user access to the same external `thread_id` resolves to different
  internal conversations (structurally impossible to share) — tested.
- Memory is message state only; identity/authorization stays in a fresh
  `ActorContext` per request → `ToolRuntime.context` → hard RBAC.
- Prompt injection inside memory cannot change authorization (tested).
- Thread ids are UUID-validated at the API boundary; no user_id/role accepted.

## 6. API changes

- `POST /assistant/chat`: request gains optional `thread_id` (UUID). Response
  SSE events `assistant_start`/`assistant_complete` now include `thread_id`
  (external, safe) and `memory_mode`.
- `GET /assistant/capabilities`: `memory_enabled` = `memory_mode != "none"`;
  new `memory_mode` field. No checkpoint internals exposed.

## 7. Frontend

`AssistantChat.tsx` generates a `thread_id` (`crypto.randomUUID()`) per chat,
sends it on every turn, adds a "New chat" action (new id + clears visible
history), and shows a "Session memory" (process-local) badge when enabled.
`lib/assistant.ts` sends `{message, thread_id}`; types updated. Visible history
is React state only; the backend now holds the real conversation.

## 8. Summarization configuration

Settings: `ICE_AI_MEMORY_MODE` (default `saver`), `ICE_AI_SUMMARIZE_TRIGGER_KIND`
(`messages`), `ICE_AI_SUMMARIZE_TRIGGER_VALUE` (40), `ICE_AI_SUMMARIZE_KEEP`
(20). The trigger is a `(kind, value)` tuple; the summarization model is the
configured model (or a test fake).

## 9. Context-editing configuration

Settings: `ICE_AI_CONTEXT_EDIT_TRIGGER` (approx tokens, 5000) and
`ICE_AI_CONTEXT_EDIT_KEEP` (3). Wired as
`ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger, keep, clear_tool_inputs=True)])`.

## 10. Tests

New `tests/test_assistant_memory.py` (11 tests): same-thread recall (3-turn
Green-Heights example), different-thread isolation, cross-user isolation,
client-cannot-inherit-admin-thread, fresh-ActorContext-per-request, injection-
inside-memory, tool denial on later turns, fresh-saver-clears-memory,
summarization (fires, recent retained, summary in context), context-edit
(clears old tool uses), and the metrics comparison. AI suite 56 → 67.

## 11. Labs

- `backend/ai_labs/memory_compare/` — stateless vs InMemorySaver vs
  summarization on the observable message flow.
- `backend/ai_labs/context_editing/` — stored vs active model context with
  `ClearToolUsesEdit` (1467 → 754 chars, `[cleared]` placeholder).

## 12. Metrics (deterministic fake model)

| mode | context messages (final call) | stored messages |
|---|---|---|
| none | 4 | — |
| saver | 8 | 8 |
| summarize | 4 | 4 |
| context_edit | 8 | 8 |

Interpretation: stateless forgets; saver sends full history; summarize
compresses; context editing only pays off with large/repeated tool results
(demonstrated in the lab). Token claims are NOT made from fakes — real provider
measurement is a W7.x follow-up.

## 13. Logging changes

`assistant.run.started`/`assistant.run.completed` gain `thread_id_safe`,
`memory_mode`, `context_message_count`, and (best-effort, memory-only)
`stored_message_count`. No conversation/summary/tool-result contents logged.

## 14. Known limitations

- Memory is process-local (restart/worker boundaries lose it).
- Summarization adds a model call when it fires (cost measured, not assumed).
- `context_message_count` is the per-turn observable trace, not the total
  history; the true model-input size is measured from the fake's recorded calls
  in the metrics test.
- Threads are not listed/persisted (no `GET /assistant/threads`); the frontend
  keeps a simple in-page conversation.

## 15. Deviations from plan

- `GET /assistant/threads` was NOT added (InMemorySaver can list, but a
  persisted conversation UI is out of W7.1 scope; frontend keeps thread ids in
  page state).
- No custom `AgentState` field (`active_project_id`) was added: the LLM resolves
  project references from message history, so state would be demonstration-only.
- `SummarizationMiddleware`'s trigger/keep use the pinned `(kind, value)` +
  `keep` API; the summarization model defaults to the configured model.

## 16. Verdict

**SAFE FOR W7.2.** Memory, thread isolation, middleware experiments, tests,
labs, and docs are complete; no migration introduced; AI-1 stateless path
remains available via `ICE_AI_MEMORY_MODE=none`.
