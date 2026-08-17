# Weekend-07 Complete — ICE Copilot: Final Program Review

**Status:** COMPLETE.
**Date:** Aug 15, 2026.
**Source of truth:** code/tests (this file is the canonical engineering/security
record; `docs/AI_W7_IMPLEMENTATION_SUMMARY.md` is the simple personal learning
reference).

---

## 1. Overall architecture

A single FastAPI monolith serving the ICE Copilot through a stable, safe SSE
contract. The AI harness is `create_agent` (langchain 1.3.15 / langgraph
1.2.11-family, pinned) with `context_schema=ActorContext` as the PUBLIC
runtime-context API: the authenticated actor is injected via `context=actor` and
reaches every tool through `ToolRuntime.context`. Provider/model/keys stay
server-side. The agent is assembled in one place (`build_agent`): a fixed,
inspectable middleware order plus a role-filtered tool catalog. Identity,
authorization and audit are never in the model's hands.

## 2. Concepts from the course through Weekend 07

create_agent · ToolRuntime/context · per-tool RBAC · multi-provider models ·
SSE streaming · execution logging · InMemorySaver + threads · summarization ·
context editing · web search + external tool retry · the full middleware stack
(limits, retry, fallback, PII, selector, todo, tool-error) · HumanInTheLoop ·
Command(resume) · LLMToolEmulator · InMemoryStore · return_direct ·
wrap_model_call · structured output.

## 3. AI-1 foundation

`context_schema=ActorContext` (frozen user_id+role) injected per invocation;
seven original read-only tools with hard deterministic self-RBAC; multi-provider
factory (openai/anthropic/groq/openrouter); SSE `POST /assistant/chat` +
`GET /assistant/capabilities`; safe structured execution logging with
request_id/token/tool metrics and PII scrubbing.

## 4. W7.1 — memory/context

User-namespaced threads (`{user_id}::{thread_id}`) on the process-level
InMemorySaver; summarization and context-editing middleware; thread listing;
process-local durability limitation documented. Cross-user thread access is
structurally impossible and tested.

## 5. W7.2 — web/retry

Tavily-compatible `web_search` via a direct async httpx wrapper (no SDK);
`ToolRetryMiddleware` scoped to transient external failures only (deterministic
DB/domain errors never retried — test-pinned); internal+external multi-tool
synthesis with citations.

## 6. W7.3 — middleware/resilience

Explicit `build_middleware` order: PII (input) → memory → ModelCallLimit →
ModelRetry → ModelFallback → ToolSelector → ToolCallLimit (global + web) →
ToolRetry (web). Verified APIs, pinned-version gotchas (e.g. ToolCallLimit
enforces only with thread_limit + exit="end" + checkpointer) recorded. Catalog
expanded to 15 read-only tools with per-tool RBAC.

## 7. W7.4 — HITL/actions

HumanInTheLoopMiddleware interrupts only the two low-risk mutating tools
(`create_task`, `create_daily_site_log`); decisions approve/edit/reject/respond
via `POST /assistant/resume` → `Command(resume=...)` on the same user-owned
thread. Frontend approval card (Approve/Edit/Reject). Emulator validates
sensitive decision paths with zero DB writes.

## 8. Final tool catalog (17)

Read-only (15): list_projects, get_project, get_project_health, get_project_
budget, get_project_inventory, get_project_inventory_movements, get_purchase_
orders, get_purchase_order_deliveries, get_billing_milestones, get_invoices,
get_project_tasks, get_daily_site_logs, get_job_costs, get_my_notifications,
web_search. Mutating (2, HITL-guarded, default OFF): create_task,
create_daily_site_log. Every tool self-authorizes from ToolRuntime.context.

## 9. Final middleware stack

PII(email+phone, redact, input) → memory (summarize/context-edit per mode) →
ModelCallLimit(run 8) → ModelRetry(max 1, transient-only, backoff) →
ModelFallback(server-side, optional) → LLMToolSelector(measurement-gated, OFF)
→ ToolCallLimit(run 15, thread-cap when memory) + web per-tool cap(run 3) →
ToolRetry(web external) → TodoList(optional) → HumanInTheLoop(mutations only).

## 10. RBAC/security model

Hard per-tool deterministic authorization mirrors the REST routes
(`project_access` helpers, archived-readonly, M6 client shape). Role allow-lists
are defense in depth. Model can never supply identity (runtime-context only).
Mutating roles = admin + site supervisor (REST parity); procurement/client never
mutate.

## 11. Memory/security model

Threads are server-namespaced; memory is message state only, never auth; HITL
resume is ownership-validated; prompt injection can alter what a thread contains
but never who owns it or what a tool may return.

## 12. Web trust model

web_search is admin/procurement only, results bounded and flagged
non-authoritative, query/result PII scrubbed, retried only for transient
external failures, never for DB/domain errors.

## 13. Mutation/HITL model

Propose → HITL interrupt → human decision → resume on the user-owned thread →
tool re-checks ICE RBAC/validation → record_audit + transaction → result.
Approval never bypasses RBAC (client-approve test proves denial). Double-resume
executes nothing twice (langgraph semantics) + domain-level duplicate guard for
site logs.

## 14. Learning labs (ai_labs/)

toolruntime_context · agent_loop · structured_output · create_agent_vs_manual ·
memory_compare · context_editing · web_multi_tool · retry_backoff ·
middleware_order · model_resilience · pii · tool_error · todo_middleware ·
tool_selector_benchmark · hitl_lifecycle · llm_tool_emulator · inmemory_store ·
return_direct · tool_gating · report_workflow. All self-contained, ruff-clean,
never imported by `app/`, each with a README.

## 15. Tests

Backend suite grew from 390 → **465** tests (430 baseline + 35 new W7.4; the AI
suite is 127). All deterministic fake models, real Postgres. Gates: ruff 2=2,
mypy 10=10 (config re-baselined), oxlint 1=1, frontend build PASS, git diff
--check clean, secret scan clean.

## 16. Frontend

React Copilot: conversation memory + thread list, web-search flag, approval card
(Approve/Edit/Reject with editable fields), stable SSE client, capability-driven
UI. No raw LangGraph structures exposed.

## 17. Logging/metrics

`ice.ai` structured events: run started/completed, model started/completed,
tool started/completed, authorization denied, hitl interrupted/resumed,
mutation started/completed, resume completed. Safe fields only; PII scrubbed;
no identities/secrets/checkpoints in logs.

## 18. Product vs learning-only features

PRODUCT: read-only catalog, memory threads, web search+retry, PII email/phone,
limits, model retry, HITL mutations (default OFF), structured logging.
OPTIONAL/measurement-gated: model fallback, tool selector, Todo. LEARNING ONLY:
custom Aadhaar/PAN detectors, ToolErrorMiddleware, emulator, InMemoryStore,
return_direct, dynamic gating, report workflow lab, middleware-order lab.

## 19. Known limitations

InMemorySaver/InMemoryStore are process-local (restart loses memory and pending
approvals; not multi-worker safe). Mutations default OFF. Live provider smoke
skipped (OpenRouter daily quota, no Tavily key). Tool-selector savings are a
token proxy pending live measurement. Push of the earlier AI-1 commit is still
pending.

## 20. Deferred (Weekend 08+)

RAG/embeddings/vector DB · MCP · multi-agent/sub-agents · autonomous/background
agents · advanced semantic long-term memory · durable threads/approvals · live
selector cost benchmark · new observability platform.

## 21. Final security checklist

- [x] Auth required on every AI endpoint (Bearer JWT; no public AI surface).
- [x] Identity via runtime context, never model args.
- [x] Per-tool deterministic RBAC + project isolation + archived read-only.
- [x] Thread ownership user-namespaced; cross-user resume impossible.
- [x] HITL approval cannot escalate (client approve → still denied).
- [x] Mutations default OFF; only low-risk, HITL-guarded, audited.
- [x] No secrets/keys in code, configs, logs, or SSE.
- [x] PII redacted at input and in logs; PRJ/PO codes never classified as PII.
- [x] Retry scoped to transient external failures; RBAC errors never retried.
- [x] No DB migration; no new tables.
- [x] `record_audit` canonical for business history; AI logs operational only.
- [x] SSE contract stable; raw LangGraph state never exposed.

## 22. Final verdict

**WEEKEND-07 COMPLETE — SAFE TO REVIEW/COMMIT.** All concepts taught through
Weekend 07 are implemented, measured, and security-reviewed; the read-only
product baseline is preserved with mutations behind an explicit off-by-default
flag and an HITL gate; the full test suite and quality gates pass. No
commit/push performed.
