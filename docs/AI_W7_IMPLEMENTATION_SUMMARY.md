# Weekend-07 Complete — ICE Copilot Learning Summary

Plain-language, personal learning reference for the W7.1–W7.4 checkpoints.
Technical canonical records live in `docs/AI_W7_1_IMPLEMENTATION_REVIEW.md`
and, at the end of the program, `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md`.

---

# W7.1 — Memory & Context Intelligence

## 1. Why AI-1 forgot previous turns

AI-1 was stateless: every `/assistant/chat` request built a fresh agent and a
fresh conversation. The model only ever saw the current message, so turn 2
could not know what turn 1 said. That is fine for a stateless API but wrong
for a real assistant.

## 2. What InMemorySaver does

`InMemorySaver` is a LangGraph **checkpointer** — a store of completed agent
state keyed by a `thread_id`. When you pass it to `create_agent(checkpointer=...)`,
each turn's messages are saved, and the next turn on the same `thread_id` reads
them back and sends the history to the model.

## 3. thread_id

A conversation id. The frontend generates one (a UUID) per chat and sends it
with every message. The backend namespaces it per user, so the same external id
is safe across users.

## 4. How the same thread remembers

Same user + same `thread_id` → the checkpointer returns the prior messages →
turn 2's model call sees turn 1's messages (verified: turn 2 input contains
turn 1's user and assistant text). This is how "its" resolves in the
Green-Heights example.

## 5. How different threads stay isolated

Each thread is its own message store. A different `thread_id` = a different
conversation. Same user, different thread → no leakage.

## 6. Why ActorContext is NOT memory

`ActorContext` (user_id + role) is built fresh from the login on EVERY request
and injected via `context=` → `ToolRuntime.context`. It never lives in the
checkpoint. Memory holds MESSAGES only. So no amount of remembered text can
change who you are or what a tool will allow.

## 7. State vs context

- **Stored state**: everything the checkpointer keeps for the thread (full
  history).
- **Active model context**: the messages actually sent to the model on the next
  call. They are usually the same — until summarization/context editing shrink
  what is sent.

## 8. Process-local memory limitation

`InMemorySaver` lives in one process: restart the backend and memory is gone;
with several backend workers, memory is not shared. This is fine for learning/
dev. Persistent checkpoint storage is deliberately out of scope for W7.1.

## 9. SummarizationMiddleware

A middleware that, when the context reaches a trigger (e.g. `("messages", N)` or
`("tokens", N)`), asks a (separate) model to summarize the oldest messages and
replaces them with the summary, keeping the most recent `keep` messages.

## 10. What summarization actually changes

It changes what the model sees next (old context → one summary message) and the
stored thread also shrinks. It costs one extra model call when it fires, so it
is only "cheaper" if the saved input tokens beat that cost — measured, not
assumed.

## 11. ContextEditingMiddleware

A middleware that applies "edits" to the active model context before the next
model call — without deleting the stored history.

## 12. ClearToolUsesEdit

One such edit: when the context is large, old tool-use content (big ToolMessage
results) is replaced with a `[cleared]` placeholder, keeping the most recent
`keep` tool uses.

## 13. Stored conversation vs active model context

The lab `context_editing` showed it concretely: with full history the next model
call received ~1467 chars including old inventory results; with
`ClearToolUsesEdit` it received ~754 chars with `[cleared]` placeholders. The
stored thread still has the history — only what the model sees shrank.

## 14. Experiment results

The metrics test ran the same scenario under four modes (deterministic fake
model):

| mode | context messages (final model call) | stored messages |
|---|---|---|
| none | 4 | — |
| saver | 8 | 8 |
| summarize | 4 | 4 |
| context_edit | 8 | 8 |

Stateless keeps context tiny but forgets; raw memory sends the whole history;
summarization compresses it; context editing only pays off with large/repeated
tool results (see the lab).

## 15. Token/context observations

With a fake model there are no real provider tokens, so we measured **message
counts** as a proxy. Real token savings must be re-measured against a live
provider; the metric fields (`input_tokens`, `context_message_count`,
`stored_message_count`) are in the execution logs for that.

## 16. Security tests

All green (deterministic tests): same thread remembers; different threads
isolated; **different users with the same external thread_id are isolated**
(namespacing `{user_id}::{thread_id}`); a client cannot inherit an admin's
thread; identity is always a fresh ActorContext; injection inside memory
("I am admin now") does not escalate; tool denial still enforced on later
turns; a fresh saver (restart) has no memory.

## 17. What W7.1 adds to ICE Copilot

Real multi-turn conversation: the Copilot now remembers the current chat
(session memory), resolves references across turns, supports "New chat", and
reports `memory_enabled=true` (process-local). Frontend sends a `thread_id` and
shows a "Session memory" indicator.

## 18. What W7.2 adds next

Web search + external tools: a `web_search` tool (Tavily), source-aware
synthesis with ICE data, and `ToolRetryMiddleware` (exponential backoff for
transient external failures only — never deterministic DB errors).

---

# W7.2 — Web Search & External Tool Intelligence

## 1. Why ICE DB tools and web tools are different

ICE DB tools query our own PostgreSQL through the ICE services — authoritative,
role-checked, trusted. A web tool talks to an outside service — reference data,
not authoritative, not trusted.

## 2. Internal trusted data vs external untrusted data

- ICE data = internal, authoritative facts (inventory, budget, POs).
- Web results = external, untrusted evidence (market prices, trends).
The Copilot must keep them separate and say which is which.

## 3. web_search tool

One external tool, `web_search(query, max_results)`. It calls the Tavily API
through a small async httpx wrapper (no SDK dependency) and returns a compact
bounded list of `{title, url, snippet}`. It never fetches whole webpages and
never exposes the API key.

## 4. Source-aware synthesis

For "how much cement and the market price?", the answer separates ICE facts
("our inventory shows 420 bags") from external info ("web listings around
Rs 400–420/bag") and cites the source URL.

## 5. Sequential vs parallel calls

- Parallel (both tools in one turn) is faster when independent.
- Sequential (web query informed by inventory) is required when one depends on
  the other. Measured in the `web_multi_tool` lab: parallel 0.31s / 2 calls vs
  sequential 0.51s / 3 calls.

## 6. ToolRetryMiddleware

Retries failed tool calls with backoff — but we scope it to `web_search` only
and filter to a transient exception class, so ICE DB tools are never retried.

## 7. Transient vs deterministic failure

- Transient: timeout, connection drop, 5xx/429 — retry is appropriate.
- Deterministic: `not_permitted`, `not_found`, malformed query, RBAC denial —
  never retry.

## 8. Exponential backoff

Each retry waits `initial_delay * backoff_factor ** retry_number` seconds
(verified in the `retry_backoff` lab: 0.1 → 0.2 → 0.4 with factor 2).

## 9. Retry timing example

`initial_delay=0.1`, `backoff_factor=2`, `jitter=False` → real waits measured
as 0.10s, 0.20s, 0.40s between the four attempts.

## 10. Why RBAC errors are never retried

Retrying a denial is pointless and wasteful — the tool re-checks the same
deterministic rules and would deny again. The retry middleware is scoped to
`web_search` and only matches the transient exception class, so ICE RBAC errors
never enter the retry path (test-pinned).

## 11. safe_tool / retry interaction

ICE tools convert errors to safe dicts via `safe_tool` — but if that swallowed
the transient exception before the middleware saw it, retry would never happen.
So `web_search` deliberately lets transient exceptions PROPAGATE to
`ToolRetryMiddleware`; only after retries are exhausted does a safe
"external service temporarily unavailable" message reach the model.

## 12. Logging/metrics

External tools are flagged in the run logs: `external=true`,
`search_result_count`, `result_chars` — plus the existing model/tool/token
metrics. The API key and raw responses are never logged.

## 13. Experiment findings

- Retry: fail-fail-success → exactly 3 provider calls; exhaustion → safe error;
  non-retryable → 1 call.
- Sequential vs parallel: parallel is ~40% faster for independent tools.
- Trust: injected "ignore instructions" search text is returned as data, and
  the system prompt forbids following it.

## 14. ICE example

"How much cement do we have in Project X and what is the current market price?"
→ `get_project_inventory` + `web_search` → "Inventory: 420 bags. Web references
around Rs 400–420/bag (source link)."

## 15. Limitations

Default OFF (needs a Tavily key); no live smoke this checkpoint (no key
configured); retry/attempt counts are not surfaced per-attempt in the stream
(the exhausted failure is); parallel is not always better.

---

# W7.3 — Middleware & Resilience

## 1. The middleware stack (one factory, ordered)

`app/ai/middleware.py` builds the agent's middleware list in a fixed order:
PII (input) → memory → ModelCallLimit → ModelRetry → ModelFallback →
ToolSelector → ToolCallLimit (global + web per-tool) → ToolRetry (web). Order
matters (see `ai_labs/middleware_order/`): limits and PII gate early, retry and
fallback react to provider failures, tool limits sit next to the tools they
protect, and the retry-aware web tool runs last so transient web failures get
their own retry.

## 2. Config knobs (all env-gated)

`ICE_AI_MODEL_RUN_LIMIT=8`, `ICE_AI_TOOL_RUN_LIMIT=15`,
`ICE_AI_WEB_TOOL_RUN_LIMIT=3`, `ICE_AI_MODEL_RETRY_MAX_RETRIES=1` +
backoff, `ICE_AI_FALLBACK_PROVIDER/MODEL`, `ICE_AI_PII_ENABLED=True` with
`ICE_AI_PII_STRATEGY=redact`, `ICE_AI_PII_CUSTOM_ENABLED=False`,
`ICE_AI_TODO_ENABLED=False`, `ICE_AI_TOOL_SELECTOR_ENABLED=False`.

## 3. ModelCallLimitMiddleware

`ModelCallLimitMiddleware(thread_limit, run_limit, exit_behavior="end")` stops
a runaway agent cleanly once the model has been called too many times in a
thread or run. Verified: after `run_limit` model calls the agent ends with a
clean summary message instead of looping forever.

## 4. ToolCallLimitMiddleware — the pinned-version gotcha

`ToolCallLimitMiddleware(tool_name, thread_limit, run_limit, exit_behavior)`
only **enforces** when you pass `thread_limit` AND `exit_behavior="end"` AND a
checkpointer is attached (counts are persisted in `thread_tool_call_count` /
`run_tool_call_count` state). A run-only counter without a checkpointer does
not gate in this pinned langchain version. Verified in tests. ICE sets a
`run_limit` for every tool plus a `thread_limit` for web calls; only when the
agent has memory is the thread-level enforcement active.

## 5. ModelRetryMiddleware vs ToolRetryMiddleware

Same shape, different targets. `ModelRetryMiddleware(max_retries, retry_on,
on_failure)` retries **model** calls (a predicate decides what is
retryable — ICE matches transient text in the error message, e.g. timeout,
ratelimit, 5xx); `ToolRetryMiddleware` retries **tool** executions (used for
web_search). Verified: fail-fail-success → 3 provider calls; a permanent error
→ 1 call; exhaustion → safe error to the model.

## 6. ModelFallbackMiddleware

`ModelFallbackMiddleware(primary, secondary, ...)` switches to the backup
provider when the primary fails. Verified: primary down → `backup-ok`; primary
recovers → primary serves. ICE's fallback provider/model are server-side config
(`ICE_AI_FALLBACK_PROVIDER/MODEL`), never user-selectable — a user can't force
a particular provider/model (policy). `ai_labs/model_resilience/` compares
retry vs fallback.

## 7. PII — what the built-ins do (and don't)

Pinned langchain PIIMiddleware built-in types: email, credit_card, ip,
mac_address, url — **phone is NOT built-in**. ICE ships custom regex detectors
in `app/ai/pii.py` (email, phone, Aadhaar, PAN) used by the middleware and by
`mask_pii_text` for logs. Strategies: `redact`/`mask`/`block`/`hash` —
verified in `ai_labs/pii/`. Product default: email + phone, redact, input only
(project codes like `PRJ-2026-0001` are not PII and stay usable by tools).

## 8. ToolErrorMiddleware — learning only

ICE tools already convert exceptions to safe dicts (`safe_tool`), so a
central ToolErrorMiddleware is redundant and could mangle typed RBAC denials if
misordered. Product keeps `safe_tool`; the middleware stays a learning lab
(`ai_labs/tool_error/`).

## 9. TodoListMiddleware

Adds a `write_todos` planning tool for complex multi-domain reviews. OPTIONAL
(`ICE_AI_TODO_ENABLED=false`); it is a planning aid only and never an
authorization boundary — every ICE tool still self-authorizes.

## 10. LLMToolSelectorMiddleware — measurement-gated

The tool-schema proxy benchmark (`ai_labs/tool_selector_benchmark/`) estimates
BASELINE ~1735 main-model schema tokens vs SELECTOR ~308 main-model + ~430
selector-model tokens over a 5-question set. Saves main-model schema cost even
counting the selector call — but it is a proxy, so `ICE_AI_TOOL_SELECTOR_ENABLED`
stays OFF until a live benchmark confirms real savings. The selector only
narrows the role-authorized toolset; it is never the RBAC boundary.

## 11. Tool catalog now 15 tools

Added `get_project_tasks`, `get_daily_site_logs`, `get_billing_milestones`,
`get_invoices`, `get_job_costs`, `get_project_inventory_movements`,
`get_purchase_order_deliveries` — all read-only, project-scoped, RBAC-gated in
`app/ai/security.py` (admin/procurement all; supervisor 9; client 7).

## 12. Tests & gates

`tests/test_middleware.py` (13 tests) plus the existing AI suites → **96 AI
tests passing**. ruff/mypy/oxlint gates PASS against baselines; frontend build
green; all labs self-contained (never imported by app/, no network/DB).

## 13. Limitations

- Live provider smokes skipped: OpenRouter free tier hit its daily 429 limit
  and no Tavily key is configured — deterministic tests/labs cover behavior.
- The tool-call thread-limit gotcha (section 4) means memory-less runs rely on
  run-limit counting only.
- Selector savings are a token proxy; no live cost measurement yet.

---

# W7.4 — HITL, Tool Emulation & Controlled Actions

## 1. Why read-only AI is safer

Until W7.4 every Copilot tool only READ. Reads can leak, but they cannot corrupt:
no task, log or ledger entry can be written by a prompt. That made the AI safe
to give to every role. Mutations change data, so they need MORE controls.

## 2. Why mutations need more controls

A model can be tricked (prompt injection) or mis-parse intent. If it could write
to the DB directly, a bad prompt could create fake tasks or site logs. So a
mutation must clear THREE gates: the model proposes it, a HUMAN approves it
(HITL), and the ICE role/project rules still allow it.

## 3. What HumanInTheLoopMiddleware does

It watches the model's tool calls. When the model proposes a MUTATING tool, the
middleware PAUSES the run and asks for a human decision. Read-only tools keep
running normally — only the two mutating tools interrupt.

## 4. Interrupt

The pause is a LangGraph interrupt: the graph stops at a checkpoint
(`next = HumanInTheLoopMiddleware.after_model`) with a description of the
proposed action, its (whitelisted) args and the allowed decisions. Verified in
`ai_labs/hitl_lifecycle/` and the tests: before the human decides, the database
and audit trail are unchanged.

## 5. Approve

`Command(resume={"decisions":[{"type":"approve"}]})` continues the graph and the
tool executes with the ORIGINAL proposed args — exactly once.

## 6. Edit

`{"type":"edit","edited_action":{...}}` executes with the EDITED values only. The
backend MERGES the human's edited fields over the original proposal (so the
project id the model proposed survives), and only the whitelisted editable
fields are exposed to the card.

## 7. Reject

`{"type":"reject","message":...}` — the tool NEVER runs; the message becomes a
`ToolMessage(status="error")` the model can answer from. Zero DB change.

## 8. Respond

`{"type":"respond","message":...}` — the human answers ON BEHALF of the tool
(useful when the answer is already known); the tool never runs. `create_task`
allows it; `create_daily_site_log` does NOT (an append-only field record should
be rejected, not fabricated).

## 9. Command(resume)

`Command` is how you wake a paused LangGraph run. Resuming replays from the
checkpoint: the interrupt is resolved with the decision, then tool execution and
the final model answer stream normally.

## 10. Thread/checkpoint requirement

HITL needs a checkpointer (a thread) to park the interrupt. W7.1's
user-namespaced `InMemorySaver` thread is exactly that. Enabling mutations
forces the "saver" memory mode so a thread always exists.

## 11. HITL vs RBAC

HITL is an EXTRA layer, NOT authentication/authorization. Even after a human
approves, the tool still re-checks role + project rules from
`ToolRuntime.context`. Tested: a client's approved `create_task` still fails; a
supervisor cannot create tasks on a project they aren't assigned to; an ARCHIVED
project stays read-only. Approval never grants access.

## 12. LLMToolEmulator

Lets the agent exercise a sensitive tool's DECISION PATH (does it pick the tool?
what args? what does it say next?) with a synthetic result — the real function
never runs. Used to vet `receive_purchase_order`/`record_job_cost` WITHOUT
enabling them. Clearly labelled LEARNING/SIMULATION ONLY.

## 13. Emulator vs real execution

Emulator: DB changes = 0, audit = 0. Real approved mutation: DB + audit = 1
logical operation. The emulator validates the path before we spend the risk;
only then would a real HITL-protected tool be wired.

## 14. Context vs State vs Store

CONTEXT (`ActorContext`) = who is calling NOW. STATE (`InMemorySaver` thread) =
what happened in THIS thread. STORE (`InMemoryStore`) = data across threads,
namespaced per user. Demo: a user preference set in thread A is read in thread B;
another user cannot read it. The store is process-local and never an auth source.

## 15. InMemoryStore

Proved user-scoped cross-thread data works, but ICE does NOT add it to the
product in W7.4 (no W7.4 product use).

## 16. return_direct

`return_direct=True` returns a tool result immediately (1 model call) instead of
routing it through the model again (2 calls). Saves tokens/latency but loses the
model's framing. LEARNING ONLY for ICE — tool results are data, not final copy.

## 17. Dynamic tool gating

`wrap_model_call` can hide tools per request (defense in depth / token
reduction), but it is NOT authorization. ICE already prunes the role menu
statically, so this stays a concise lab.

## 18. Make-me-a-report workflow

"Make me a weekly report for Green Heights" — the agent gathers read-only data
(health, tasks, budget, inventory, POs, site logs) and emits a structured
`ProjectWeeklyReport` (10 sections incl. risks + recommended actions) validated
by Pydantic. Read-only ⇒ NO HITL. Kept as a lab in W7.4.

## 19. Experiments/results

- HITL: approve→1 mutation; edit→edited args; reject/respond→0; cross-user
  resume blocked; double-resume executes nothing twice.
- Emulator: synthetic result, 0 executions.
- Store: same-user cross-thread; different-user isolated.
- return_direct: 2 vs 1 model calls.
- Gating: model-visible set shrinks; hard RBAC unchanged.

## 20. Final Weekend-07 Copilot capabilities

Memory threads + summarization; web search + retry; full middleware stack
(limits/retry/fallback/PII/selector); 15 read-only tools; 2 HITL-guarded
mutations; safe SSE approval cards; structured report workflow.

## 21. Limitations

- Interrupts/threads are process-local (InMemorySaver) — a restart loses pending
  approvals; documented, not a production durability claim.
- Mutations default OFF (`ICE_AI_MUTATIONS_ENABLED=false`); the product stays
  read-only until explicitly enabled.
- No live smoke this checkpoint (provider quota + no Tavily key); deterministic
  tests/labs cover behavior.

## 22. What remains for Weekend 08+

RAG/embeddings, MCP, multi-agent/sub-agents, autonomous agents, advanced semantic
long-term memory, durable approvals/threads, and a live cost benchmark for the
tool selector — all explicitly deferred.

---

# Weekend-07 Close-Out

**All concepts taught through Weekend 07 are now implemented.** W7.1
memory/context, W7.2 web/retry, W7.3 middleware/resilience, and W7.4
HITL/actions landed, were measured, and were security-reviewed. The final
program record is `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md`.

## Double-resume safety, simply

A pending approval is **single-use**. LangGraph records the interrupt in the
thread's checkpoint; the first `approve` consumes it and the tool runs exactly
once. Replaying the same approve on the same thread finds no pending interrupt
and answers `no_pending_approval` — a safe no-op. The mutation count and the
audit trail stay at exactly one each. This is now pinned by a regression test
(`test_hitl.py::test_double_resume_never_duplicates_mutation`).

## Why HITL approval must be single-use

Approval is the human's explicit "yes, run this proposal". If the same approval
could run the tool twice, a network retry or a double-clicked button would
create two tasks or two site logs — silent duplicate mutations on an append-only
audit trail. One approval = one execution; anything after that is either a fresh
proposal or a rejection.

## Final test baseline (verified Aug 18, 2026)

- Backend: **462 passing** (real Postgres), of which **128 are AI tests**.
- Frontend: `npm run build` + `npm run lint` (oxlint) PASS.
- Gates: ruff 2=2 PASS, mypy 10=10 PASS, oxlint 1=1 PASS.
- All 20 `ai_labs/` demos run clean; secret scan clean.

## Current known limitations

- Thread memory and pending approvals are process-local (InMemorySaver) — a
  restart loses them.
- Mutations default OFF (`ICE_AI_MUTATIONS_ENABLED=false`); the product stays
  read-only until explicitly enabled.
- No live provider smoke (OpenRouter daily quota; no Tavily key) — deterministic
  tests/labs cover behavior.

## Next AI work waits for Weekend 08+

The course currently ends at Weekend 07 / Class 12. There is **no Weekend 08+
material yet**, so no new AI milestone is invented: the workstream pauses here.
When the user/course provides Weekend 08+ content, implementation resumes from
`docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md` §20 (deferred). ICE feature
development (Phase 5+) can resume independently on request.
