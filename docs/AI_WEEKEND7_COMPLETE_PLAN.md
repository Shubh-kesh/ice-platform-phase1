# ICE Copilot — Weekend 07 Complete: Implementation Plan

**Status:** PLANNING ONLY (no code, dependencies, migrations, or commits created
by this document).
**Date:** Aug 15, 2026.
**Strategy shift (owner):** instead of spreading the remaining Weekend-07
concepts across many small milestones, implement ALL useful concepts taught
through Weekend 07 into the ICE Copilot, in four checkpoints (W7.1–W7.4).
Fundamentals are already understood; the goal is a genuinely capable Copilot
that exercises every taught concept, explores deeper related LangChain features
(current official docs, for concepts already taught), measures behavior with the
AI-1 execution logging, and keeps genuinely untaught architecture families
deferred.

**Source of truth:** code/tests + the course repository
(`mayank953/Live-Class-2026`, verified through Weekend 07 / Class 12) +
`docs/AI_ASSISTANT_ROADMAP.md`, `docs/AI1_IMPLEMENTATION_*`, `docs/AI_CONTEXT.md`,
`docs/CURRENT_STATE.md`, `docs/SESSION_HANDOFF.md`.

---

## 1. Verified Weekend-07 concepts (re-verified Aug 15, 2026)

Course ends at **Weekend 07 / Class 12** (no Weekend 08+ in the repo tree).
Notebook imports confirm the exact middleware surface on the pinned stack
(`langchain.agents.middleware`): `ModelCallLimitMiddleware`,
`ToolCallLimitMiddleware`, `ModelFallbackMiddleware`, `ModelRetryMiddleware`,
`PIIMiddleware`, `TodoListMiddleware`, `LLMToolSelectorMiddleware`,
`ToolErrorMiddleware`, `ToolRetryMiddleware`, `SummarizationMiddleware`,
`HumanInTheLoopMiddleware`, `LLMToolEmulator`, `ContextEditingMiddleware`,
`ClearToolUsesEdit`, plus `wrap_model_call`. Supporting taught concepts:
`create_agent`, `init_chat_model`, `@tool`/`ToolRuntime`, `InMemorySaver` +
`thread_id`, `InMemoryStore` (long-term store), `return_direct`, tool gating via
`wrap_model_call`, structured output (`method="json_schema"` ≈ ProviderStrategy,
`method="function_calling"` ≈ ToolStrategy), exponential backoff.

## 2. Already implemented by AI-1

- `create_agent(..., context_schema=ActorContext)` + `context=actor` +
  `ToolRuntime[ActorContext]` (public runtime-context API).
- Seven read-only ICE tools; hard deterministic per-tool RBAC; role-filtered
  catalog as defense-in-depth; M6 client isolation.
- Multi-provider model factory (openai / anthropic / groq / openrouter).
- SSE streaming (`POST /assistant/chat`), capabilities, React `/assistant`.
- Safe execution logging (`app/ai/logging.py`, NORMAL vs `ICE_AI_DEBUG`),
  usage/token/tool metrics, `request_id`, `tool_counts`.
- Learning labs: `toolruntime_context`, `agent_loop`, `structured_output`,
  `create_agent_vs_manual`.
- Baseline: 390 backend tests (56 AI), gates PASS.

## 3. Remaining concepts to implement (this plan)

Conversation memory/threads (W7.1) · summarization/context-editing (W7.1) ·
web search + retry (W7.2) · full middleware stack (W7.3) · tool selector
(W7.3) · HITL + tool emulator + controlled mutations (W7.4) · InMemoryStore
experiment (W7.4) · return_direct / wrap_model_call gating experiments (W7.4).

---

## W7.1 — CONVERSATION MEMORY & CONTEXT INTELLIGENCE

### Scope

- **InMemorySaver** checkpointer + `thread_id` → true multi-turn backend memory.
- Multiple independent conversations per user; **thread ownership/isolation**
  (server-namespaced, cross-user impossible).
- Custom `AgentState` **only where useful** (e.g., a `project_context` hint
  field for disambiguation); AgentState is conversation state, NEVER auth.
- `SummarizationMiddleware`, `ContextEditingMiddleware`, `ClearToolUsesEdit`.
- Context-strategy experiments (A–D) measured with the AI-1 logging.

### Files (expected)

- `backend/app/ai/memory.py` (new): checkpointer wiring, thread-key
  namespace (`user_id::thread_id`), thread listing, ownership resolution.
- `backend/app/ai/agent.py`: `build_agent(..., checkpointer=..., state_schema=...)`
  + thread config plumbing; `stream_assistant`/`run_agent` accept
  `thread_id: str | None`.
- `backend/app/api/v1/assistant.py`: `POST /assistant/chat` gains optional
  `thread_id`; new `GET /assistant/threads` (user-scoped listing, learning).
- `backend/app/ai/agent_state.py` (new, small): optional `IceAgentState`
  (messages + `project_context`), if the experiments justify it.
- Frontend: conversation list + per-conversation `thread_id` sent on each turn.
- Tests: `backend/tests/test_assistant_memory.py`; labs under
  `backend/ai_labs/memory_compare/` and `backend/ai_labs/context_editing/`.

### Dependencies

None new — `InMemorySaver` ships in the pinned `langgraph` stack;
`SummarizationMiddleware`/`ContextEditingMiddleware`/`ClearToolUsesEdit` are in
the pinned `langchain.agents.middleware`.

### Configuration

`ICE_AI_MEMORY_ENABLED` (default false → AI-1 stateless behavior preserved),
`ICE_AI_SUMMARIZE` (false), `ICE_AI_SUMMARIZE_TRIGGER_TOKENS`, `ICE_AI_SUMMARIZE_KEEP_MESSAGES`.
All server-controlled; the request body adds only `thread_id` (client-chosen
friendly id), never identity.

### Security — threads can never bypass ActorContext

```
HTTP user ─► ActorContext(user_id, role) ─► context=actor ─► ToolRuntime.context ─► RBAC
                                    ^ conversation state (messages) is separate
```
- The server stores threads as `{user_id}::{thread_id}`. A client sending
  `thread_id="abc"` always resolves to *their own* namespace; **User B can
  never reach User A's thread** even with the same id.
- Thread listing is user-scoped (`WHERE owner == actor.user_id` semantics via
  the namespaced keyspace; no DB migration — derive from the checkpointer key
  prefix).
- Every tool still re-authorizes from `ToolRuntime.context` on every turn;
  remembered "project context" is a hint, never an access grant.
- Prompt-injection can alter what a thread *contains*, but never who owns it or
  what a tool is allowed to return.

### Tests (must include)

- User A creates thread; User B tries the **same** `thread_id` → different
  conversation, no cross-user leakage.
- Turn 1/2/3 context recall (Green Heights example) works.
- Memory does not change RBAC: client with memory still denied budget;
  supervisor still denied unassigned project; injection still denied.
- Long-conversation: token growth bounded (or summarized) in each strategy.
- Safe logs: no message contents / no identity in logs beyond role.

### Experiments (measured with existing logging fields)

A. no memory · B. raw `InMemorySaver` · C. `SummarizationMiddleware` ·
D. `ContextEditingMiddleware`/`ClearToolUsesEdit`.
Measure per strategy: context/message count, input/output tokens, model calls,
tool calls, latency, recall correctness (targeted recall questions).

### Acceptance / STOP point

Multi-turn recall works end-to-end (the Green Heights 3-turn example); thread
isolation test passes; AI-1 stateless path still works when memory disabled;
no migration introduced. STOP after W7.1 experiments recorded.

---

## W7.2 — WEB SEARCH & EXTERNAL TOOL INTELLIGENCE

### Scope

- Narrow **`web_search(query)`** tool (Tavily — matches the course's TripMate
  stack). Managed search API = SSRF-safe by design (server-side fetch, no
  arbitrary URL), bounded results, no arbitrary webpage execution.
- Source-aware synthesis: ICE DB tools + `web_search` + LLM synthesis.
- `ToolRetryMiddleware` for **transient external/network** failures with
  exponential backoff; **deterministic DB validation errors are never retried.**

### Files

- `backend/app/ai/tools/web.py` (new): `web_search` tool (A/P only by default),
  bounded results (top-k, char budget via `bound_items`-style), timeout.
- `backend/app/ai/security.py`: add `TOOL_WEB_SEARCH` to the A/P allow-list
  only; label "Web search".
- `backend/app/ai/agent.py`: wire `ToolRetryMiddleware` (external-only,
  exception-filtered) when the agent is built.
- Config: `ICE_AI_TAVILY_API_KEY` (secret, gitignored), `ICE_AI_WEB_SEARCH_ENABLED`,
  `ICE_AI_WEB_SEARCH_MAX_RESULTS`, `ICE_AI_WEB_SEARCH_TIMEOUT_S`,
  `ICE_AI_WEB_SEARCH_RETRIES`/`BACKOFF`.
- Tests: `backend/tests/test_web_search.py`; lab `backend/ai_labs/web_retry/`.

### Dependencies

`tavily-python` (pinned) — **owner decision** (or an httpx-only Tavily wrapper
to avoid the dependency; prefer the official client if it matches the course).
No other new deps (`ToolRetryMiddleware` is in the pinned stack).

### Security

- `web_search` is admin/procurement only (procurement prices materials).
- Query/result PII scrubbed before logging; results flagged
  non-authoritative ("verify before purchase").
- `ToolCallLimitMiddleware` bounds external calls (W7.3); never retried for
  validation/domain errors.

### Tests

- Multi-tool synthesis (cement on hand + market price) with deterministic fake
  web tool.
- Retry fires ONLY for transient/network errors, NOT for `not_found`/
  `not_permitted`/validation.
- Exponential backoff timing; bounded results; timeout handling; RBAC (client/
  supervisor denied web_search).

### Experiments

Sequential vs parallel tool calls · induced external failure · retry count ·
backoff delay timing · token/latency impact of search results.

### Acceptance / STOP point

The cement+price and steel-PO-rate questions answer from both ICE + web tools
with citations; retry semantics proven; no arbitrary URL fetch. STOP after W7.2.

---

## W7.3 — COMPLETE MIDDLEWARE & RESILIENCE STACK

### Scope

Implement and experiment with: `ModelCallLimitMiddleware`,
`ToolCallLimitMiddleware`, `ModelFallbackMiddleware`, `ModelRetryMiddleware`,
`PIIMiddleware` (+ custom detectors), `ToolErrorMiddleware`,
`ToolRetryMiddleware`, `TodoListMiddleware`, `LLMToolSelectorMiddleware`;
re-inspect `ContextEditingMiddleware`/`ClearToolUsesEdit` (already used in
W7.1). For **every** middleware record: ICE use case · PRODUCT vs LEARNING ·
configuration · ordering · interactions · induced-failure experiment · metrics ·
tests · expected security behavior.

### Per-middleware plan

| Middleware | ICE use case | PRODUCT vs LEARNING | Key notes |
|---|---|---|---|
| `ModelCallLimitMiddleware` | Bound runaway/large runs (observe via logging first) | PRODUCT (sanely configured) | low artificial limit test vs normal production limit; `run_limit`/`thread_limit` |
| `ToolCallLimitMiddleware` | Limit `web_search`; expose the portfolio N+1 (`list_projects=1`, `get_project_health=12`) as an experiment | PRODUCT (external tools) / LEARNING (N+1) | per-tool caps; N+1 becomes an AI-5 tool-architecture benchmark, not silently "solved" |
| `ModelFallbackMiddleware` | Primary provider → fallback across the multi-provider factory | PRODUCT | primary deliberately fails → fallback succeeds; measure calls/latency/usage/answer |
| `ModelRetryMiddleware` | Transient 429/timeout on the SAME provider | PRODUCT | distinct from fallback; simulate 429/timeout/provider failure |
| `PIIMiddleware` | Emails/phones (ICE `users`) + learning detectors | PRODUCT (email/phone) / LEARNING (Aadhaar/PAN) | **never classify `PRJ-…`/`PO-…` codes as PII**; compare redact/mask/block/hash; evaluate input, tool result, output |
| `ToolErrorMiddleware` | Convert unexpected tool exceptions to safe model-visible errors | PRODUCT (see ToolError vs safe_tool below) | interacts with existing `safe_tool` |
| `ToolRetryMiddleware` | Transient external/network retries only (W7.2) | PRODUCT (external only) | never DB/domain errors |
| `TodoListMiddleware` | Complex "review Project X … top five actions" question | LEARNING → candidate | compare with/without |
| `LLMToolSelectorMiddleware` | Large catalog served efficiently | PRODUCT if benchmark proves it | `max_tools`/`always_include`; measure TOTAL tokens, not assumed |

### ToolErrorMiddleware vs the existing `safe_tool`

- `safe_tool` (AI-1) already converts deterministic domain/auth errors
  (`not_permitted`, `not_found`) into safe dicts and swallows unexpected
  exceptions into `internal`.
- **Recommendation (hybrid):** retain deterministic domain-safe errors inside
  tools (they encode RBAC/domain semantics and must not be re-decided by
  middleware), and let `ToolErrorMiddleware` handle the generic
  unexpected-exception → safe-message conversion at the boundary. Concretely:
  narrow `safe_tool` to the deterministic domain errors and remove its broad
  `except Exception`, delegating that to `ToolErrorMiddleware`. Trade-off:
  single responsibility (tools = domain/RBAC; middleware = resilience/error
  hygiene) vs one extra moving part to order correctly. **Owner decision** on
  whether to migrate fully in W7.3 or keep the hybrid.

### Middleware ordering (proposed starting order — verified by experiment)

```
PII (input) → ModelCallLimit → ModelRetry → ModelFallback → LLMToolSelector
→ ToolCallLimit → ToolError → ToolRetry (external) → wrap_model_call logging/gating
```
Ordering is itself an experiment (the course's "middleware ordering" lab); the
final order is chosen from measured behavior, not assumption.

### Tool-catalog expansion

Coherent taxonomy (candidate read tools, added only where they earn their
place):

| Domain | Tools |
|---|---|
| Projects & health | list_projects, get_project, get_project_health |
| Finance | get_project_budget, **get_job_costs** |
| Inventory | get_project_inventory, **get_project_inventory_movements** |
| Procurement | get_purchase_orders, **get_purchase_order_deliveries** |
| Field | **get_project_tasks**, **get_daily_site_logs** |
| Billing | **get_billing_milestones**, **get_invoices** |
| Notifications | get_my_notifications |
| External | **web_search** (W7.2) |

Not all get added automatically — each new tool needs the same hard self-RBAC,
bounded output, M6-aware role mapping, and label as the existing seven. Adding
tasks/site-logs/invoices expands the client-safe surface carefully (M6 shapes
must be preserved).

### ToolSelector benchmark

Compare A (all schemas to main model) vs B (`LLMToolSelectorMiddleware`) over a
fixed question set. Measure **TOTAL** cost = selector input/output + main
input/output; plus latency, routing accuracy, selected tools, answer
correctness. **Do not claim savings unless measured.** `always_include` =
`list_projects`; `max_tools` tuned from the benchmark.

### Configuration

Settings for each middleware (limits, retry counts/backoff, fallback provider/
model, PII strategy, selector on/off + `max_tools`). Server-controlled only.

### Files / tests / labs

- `backend/app/ai/middleware.py` (new, wiring/order) or inline in `agent.py`.
- `backend/tests/test_middleware.py` (each middleware trigger, ordering, no
  leakage, limits, fallback, retry filtering, PII).
- Labs: `backend/ai_labs/retry_backoff/`, `backend/ai_labs/fallback/`,
  `backend/ai_labs/pii/`, `backend/ai_labs/todo_middleware/`,
  `backend/ai_labs/tool_selector_benchmark/`.

### Acceptance / STOP point

Every middleware has a passing trigger test + an induced-failure experiment +
recorded metrics; selector benchmark numbers recorded (not assumed); PII
strategy documented; N+1 health-call experiment recorded. STOP after W7.3.

---

## W7.4 — HITL + TOOL EMULATION + CONTROLLED MUTATIONS

### Scope

- `HumanInTheLoopMiddleware` + `InMemorySaver`/thread continuation +
  `Command(resume=...)` (approve / edit / reject / respond).
- **Low-risk mutations first:** `create_task`, `create_daily_site_log`.
  Evaluate (do NOT enable by default): `create_purchase_order`,
  `record_job_cost`, `receive_purchase_order`.
- `LLMToolEmulator` to test mutation decision paths **without touching ICE DB**.
- Structured output where it improves the product: `ProjectActionPlan`,
  `RiskReview`, emulator-result validation (current API: `method=` on
  `with_structured_output` / `create_agent(response_format=...)`).
- `InMemoryStore` experiment (state vs context vs store) — NOT a random
  production dependency.
- `return_direct` / `wrap_model_call` tool-gating experiments (Class 10) if
  useful for exact-value tools or future gating.

### Mutation doctrine (unchanged ICE rules)

Every mutation reuses the existing ICE path: RBAC role gates, project
visibility + IDOR rules, project row locks, server-side validation,
M8 idempotency where applicable, `record_audit`, transactional notifications,
and the same transaction semantics. **HITL is an additional authorization/
control layer — never a replacement for ICE RBAC.** Mutations live behind
`assert_project_writable` etc. exactly like their REST counterparts.

### HITL architecture

```
Agent proposes mutating tool
  → HumanInTheLoopMiddleware interrupts (thread requires checkpointer)
  → SSE approval card (tool, sanitized args, reasoning-free summary)
  → Approve / Edit / Reject / Respond
  → Command(resume={"decisions": [...]})
  → tool executes ONLY if approved (edit → modified args)
  → audit + transaction commit
  → final response
```
- **Resume security:** the resume endpoint resolves the thread through the
  authenticated actor's namespace AND validates the interrupt is owned by the
  same user. Another user can never resume/approve someone else's interrupt.
- Thread + HITL state uses `InMemorySaver` (process-local; documented
  limitation — a durable approvals table would be a migration and is deferred).

### Files / tests / labs

- `backend/app/ai/tools/mutating.py` (new; `mutating: true`, HITL-guarded),
  `backend/app/api/v1/assistant.py` (resume endpoint + approval events),
  frontend approval card in `AssistantChat.tsx`.
- Tests: `backend/tests/test_hitl.py` (all four decisions, resume ownership,
  audit, idempotency, RBAC, rollback on reject, no cross-user resume).
- Labs: `backend/ai_labs/llm_tool_emulator/`, `backend/ai_labs/hitl_lifecycle/`,
  `backend/ai_labs/inmemory_store/`.

### Acceptance / STOP point

`create_task`/`create_daily_site_log` proposals flow through the full
approve/edit/reject/respond lifecycle with audit + transaction correctness;
emulator verifies decision paths with zero DB writes; resume ownership test
passes. STOP after W7.4 (Weekend-07 state complete).

---

## 8. Tool-catalog expansion plan

See the W7.3 taxonomy. Rule: add a tool only if (a) it has a real ICE use case,
(b) it gets full self-RBAC + M6-aware role mapping + bounded output + a label,
and (c) the total catalog stays serviceable (the selector benchmark informs
whether `LLMToolSelectorMiddleware` becomes necessary).

## 9. Memory/thread security design

- Thread key = `{actor.user_id}::{thread_id}` (server-side). Cross-user access
  structurally impossible; tested.
- Memory is message history only; identity/authorization stays in
  `context=actor` → `ToolRuntime.context`. AgentState may carry conversation
  hints (e.g., `project_context`) but is never an auth source.
- HITL resume is ownership-validated on the same thread.

## 10. Middleware ordering proposal

See W7.3 ordering table; final order chosen by experiment (ordering lab).

## 11. Fallback/retry design

- `ModelRetryMiddleware` = same provider, transient (429/timeout/temp failure),
  backoff.
- `ModelFallbackMiddleware` = different provider/model from the multi-provider
  factory. Keys/config remain server-side; never exposed to frontend/model or
  logs (existing logging deny-list covers them).
- `ToolRetryMiddleware` = external tools only; deterministic DB/domain errors
  never retried (test-pinned).

## 12. PII strategy

- PRODUCT: `PIIMiddleware` on emails/phones at input; strategy `redact`/
  `mask` chosen by test. `PRJ-…`/`PO-…` are NOT PII — never classified.
- LEARNING: custom regex detectors for Aadhaar/PAN; compare redact/mask/block/
  hash; evaluate at input, tool result, output.
- Logging stays PII-safe (existing `logging.py` sanitizers).

## 13. ToolSelector benchmark strategy

Fixed question set → A vs B → total tokens (selector + main), latency, routing
accuracy, selected tools, correctness. Decision to ship is gated on measured
savings.

## 14. HITL architecture

See W7.4 (flow, ownership, mutation doctrine, frontend approval card).

## 15. LLMToolEmulator strategy

Emulate the mutating tools (`create_task`, `receive_purchase_order`) during
tests: the agent's chosen tool/args flow through the emulator, which returns a
synthetic result — inspect decision path and downstream response with **zero
ICE DB writes**. Explicitly distinct from real production execution (flagged in
code/tests).

## 16. Learning-lab matrix

| Lab | Checkpoint | Hypothesis / purpose |
|---|---|---|
| `memory_compare/` | W7.1 | no-memory vs InMemorySaver vs Summarization vs ContextEditing |
| `context_editing/` | W7.1 | ContextEditingMiddleware / ClearToolUsesEdit behavior |
| `web_retry/` | W7.2 | external retry/backoff; DB errors not retried |
| `retry_backoff/` | W7.3 | exponential backoff timing (model + tool) |
| `fallback/` | W7.3 | primary fails → fallback succeeds; metrics |
| `pii/` | W7.3 | redact/mask/block/hash + custom Aadhaar/PAN detectors |
| `todo_middleware/` | W7.3 | with/without TodoListMiddleware on a complex review |
| `tool_selector_benchmark/` | W7.3 | A vs B total-cost benchmark |
| `llm_tool_emulator/` | W7.4 | emulator vs real decision path (no DB writes) |
| `hitl_lifecycle/` | W7.4 | approve/edit/reject/respond lifecycle |
| `inmemory_store/` | W7.4 | state vs context vs store with an ICE example |

Each lab: README.md (hypothesis, experiment, expected observations, metrics,
conclusion), never imported by `app/`.

## 17. Dependencies expected

- W7.1: none new.
- W7.2: `tavily-python` (or an httpx-only wrapper — owner decision).
- W7.3: none new (middleware in the pinned `langchain` stack).
- W7.4: none new.
All pinned; the existing langgraph/langchain family stays fixed.

## 18. Migration impact

**Preferred: zero DB migrations.** Threads, HITL resume, and memory live in
`InMemorySaver` (process-local; limitation documented). A future durable
threads/approvals table would require a migration and is explicitly deferred.
Mutations write to the existing ICE tables via the existing services (no new
tables).

## 19. Testing strategy

- Deterministic fake models in CI (no provider).
- Keep: hard tool RBAC, client M6 isolation, thread ownership (no cross-user
  memory), no prompt-injection bypass, safe logs, no secrets, safe streaming,
  existing ICE regressions (full 390 baseline grows).
- Live provider calls are smoke-only.

## 20. Documentation strategy

- Per checkpoint, update `docs/AI_W7_IMPLEMENTATION_SUMMARY.md` (simple
  learning reference, sections W7.1–W7.4).
- At final completion, create `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md`
  (canonical engineering/security record).
- Reuse the AI-1 execution logging for all experiments; extend only if
  genuinely required.

## 21. Risks / owner decisions

- **Thread/memory persistence** (InMemorySaver is process-local; not
  multi-worker safe) — acceptable for learning/dev; a durable store is
  deferred.
- **Tavily** client dependency vs httpx wrapper; Tavily API key management.
- **Fallback provider selection** (which secondary provider/model; keys in
  `.env`).
- **ToolError vs safe_tool** (hybrid recommended; decide in W7.3).
- **Middleware ordering** chosen by experiment, not assumption.
- **Which mutations ship** (low-risk first; sensitive evaluated but not enabled
  by default).
- **Tool-catalog breadth** (add only justified tools; selector only if
  benchmark proves it).
- **N+1 portfolio health pattern** — recorded as a benchmark, not silently
  "fixed".
- **HITL + InMemorySaver** resume survives only the process lifetime.

## 22. Recommended implementation order

W7.1 (memory) → W7.2 (web + retry) → W7.3 (middleware + selector) → W7.4
(HITL + emulation + mutations). Each is independently releasable, testable with
fake models, and keeps the security invariants intact.

## 23. Deferred — Weekend 08+ parking lot (do NOT implement)

Architecture families NOT taught through Weekend 07 remain deferred and will
not be designed or implemented in W7.1–W7.4:

- **RAG** (retrieval-augmented generation) — course Phase 3.
- **Embeddings-based retrieval** and **vector databases/stores**.
- **MCP** (Model Context Protocol).
- **Multi-agent architecture / sub-agents** (Deep Agents only mentioned).
- **Autonomous / background agents**.
- **Advanced long-term semantic memory** (beyond `InMemorySaver`/`InMemoryStore`).
- **New production observability platform** (AI-1 logging stays).

When the course adds Weekend 08+, re-run the AI-0 mapping process
(`docs/AI_ASSISTANT_ROADMAP.md` §16) and move the newly taught concepts out of
this parking lot.

## 24. Verdict

**SAFE TO BEGIN W7.1** (with owner decisions on Tavily dependency, fallback
provider pairing, and the final mutation set confirmed during W7.3/W7.4).
All Week-end-07 concepts are mapped; no untaught architecture family is
slipped in; authorization stays deterministic; threads cannot cross users;
retry is scoped to transient external failures; fallback/PII/logging stay
secret-safe; the tool-selector claim is measurement-gated; mutation paths
retain existing ICE transaction rules; AI-1 logging is reused throughout.
No implementation, commit, or push performed.
