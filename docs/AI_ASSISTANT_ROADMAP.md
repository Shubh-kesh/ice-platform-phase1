# ICE AI Assistant — Architecture & Course Mapping (AI-0, Rev 2)

> **Aug 18 note — HISTORICAL PLANNING DOCUMENT (pre-implementation).** The AI
> workstream is now implemented through **Weekend 07** and committed at
> `ce88b1f`. This file is the original AI-0 plan (course mapping + AI-1…AI-6
> sequence) kept as a historical record. For current state, see
> `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md` (canonical record),
> `docs/AI_W7_IMPLEMENTATION_SUMMARY.md` (plain-language), and
> `docs/AI_CONTEXT.md` (bootstrap). Milestone numbers below (AI-1…AI-6) are
> planning labels, not current status.

**Status:** PLANNING ONLY (AI-0, revision 2). No AI application code, no
migrations, no dependency changes, no changes to existing backend/frontend
behavior were created by this document.
**Date:** Aug 14, 2026 (Rev 2 — strategy revision approved by owner).
**Author of intent:** Owner following the Agentic AI 3.0 Specialization course
`mayank953/Live-Class-2026`, learning each concept by implementing it inside
the existing ICE Platform instead of in a separate toy project.

This is the canonical planning document for the **ICE AI Assistant** — the
gradual evolution of an in-product construction copilot driven by the course.

**Learning rule (binding):** only concepts actually covered through **Weekend 07
(Class 12, 8–9 Aug 2026)** — the latest documented class in the course
repository — may be used. Do not pull forward RAG, vector databases, MCP,
multi-agent systems, advanced persistent memory, evaluation frameworks, or
other later material unless the course has covered it.

**Advanced-topic rule (Rev 2, owner-approved):** because the owner already
understands the foundational concepts, we may use the current official
LangChain documentation to explore **advanced and adjacent features of concepts
already taught** through Weekend 07 (ToolRuntime context/state/store/streaming,
custom `AgentState`, `ProviderStrategy` vs `ToolStrategy`, tool schema design,
async tools, multiple/parallel/sequential tool calls, streaming agent/tool
progress, `SummarizationMiddleware`, `ContextEditingMiddleware` /
`ClearToolUsesEdit`, middleware composition/order, retry semantics and
exception filtering, model vs tool retry, dynamic tool selection,
usage/token/cost comparison, HITL decision flows, `LLMToolEmulator`
experiments). This permission does **NOT** extend to fundamentally new untaught
architecture families (RAG, vector databases, MCP, multi-agent systems,
autonomous background agents) — those remain parked (§15).

---

## 1. Purpose

1. Reconstruct the current ICE baseline (§2) so the AI workstream starts from
   verified fact (code/tests are ground truth).
2. Verify exactly which Agentic AI concepts the course has taught through
   Weekend 07 (§3) and map each to a concrete ICE practice (§4, §10, matrix).
3. Define the ICE AI Assistant boundary that fits the existing FastAPI monolith
   without becoming an RBAC bypass (§5, §6).
4. Define the read-only ICE tool catalog for the core copilot (§7).
5. Define a **vertical-slice milestone sequence** (AI-1…AI-6) sized so each
   milestone is a genuinely useful product increment while deepening the
   taught concepts and their advanced/adjacent corners (§12).
6. Define the **Learning Experiments** program and its isolated lab (§13).
7. Park all not-yet-taught concepts (§15) and define how Weekend 08+ is
   incorporated (§16).
8. Recommend an AI-1 implementation plan (§17).

---

## 2. Current ICE baseline (verified against source, Aug 14 2026)

### 2.1 Git / repository

- Branch `claude-development`, HEAD **`9bfe711` "feat: implement M15 purchase
  order receiving"**, **ahead of `origin/claude-development` by 1** (M15 is
  committed but **not pushed**). Working tree is **clean** (`git status --short`
  empty, `git diff --check` clean).
- Alembic head `l5d6e7f8a9b0` (M15 `deliveries`/`delivery_lines` + `po_status`
  extension); migration chain-tested in `backend/tests/test_migrations.py`.
- Docs state the backend baseline as **307 passing** (verified at M14) and the
  M15 plan expects ~345 after receiving tests; **this planning task did not
  re-run the suite** — re-verify before AI-1.

### 2.2 Architecture

Single-service monolith. React 19 + Vite SPA (TanStack Query, axios, react-router)
→ `axios -> /api/v1` (Bearer JWT) → FastAPI (`backend/app/main.py`) → async
SQLAlchemy 2.0 (asyncpg) → PostgreSQL 16. Alembic migrations. Docker Compose
dev. Redis provisioned but **unused by any code**.

- **Backend layout:** `api/v1/*` route modules hold auth, RBAC, validation,
  business logic, DB access, audit inline; a thin `services/` layer holds pure
  domain math (finance, health, inventory, receiving, purchase_orders, tasks,
  projects, idempotency, auth_tokens, google_auth, invoicing, notifications).
  `schemas/` = Pydantic request/response. `models/` = SQLAlchemy ORM.
  No repositories layer, no workers/queues.
- **Frontend:** `App.tsx` routes `/login`, `/google/callback`, `/` (Command
  Center), `/projects/:projectId`; `AppShell.tsx` provides the sidebar nav +
  header (NotificationsBell, env badge). `lib/api.ts` (axios + refresh-on-401),
  `lib/auth-context.tsx`, `types/index.ts` (single contract file mirroring
  backend schemas).

### 2.3 Relevant domain surfaces (ground truth for the tool catalog)

| Surface | Backend | Roles | Notes |
|---|---|---|---|
| Auth | `api/v1/auth.py`, `core/security.py`, `services/auth_tokens.py`, `models/refresh_session.py` | all | M9 opaque rotating refresh sessions; M11 Google. Access JWT 30m. |
| RBAC | `api/deps.py` (`require_role`, `get_current_user`), `api/project_access.py` | — | 4 roles: `admin`, `site_supervisor`, `procurement_manager`, `client`. |
| Project access | `api/project_access.py` | — | `get_project_or_404`, `get_project_for_update` (row lock), `assert_project_writable` (ARCHIVED 403), `assert_not_client`, `assert_can_view_project` (assigned-only; ARCHIVED 404 for non-A/P). |
| Projects + lifecycle | `api/v1/projects.py`, `services/projects.py`, `models/project.py` | A/P full; S assigned; C client shape | `ProjectRead` (A/P) / `ProjectReadRestricted` (S, no budget) / `ProjectClientRead` (C, tight). DRAFT→ACTIVE→COMPLETED→ARCHIVED. |
| Health | `services/health.py`, `models/health.py` | A/P/S; **C 403** (`assert_not_client`) | Deterministic SPI + budget-vs-progress + override. |
| Tasks / Gantt | `api/v1/tasks.py`, `services/tasks.py` | A/S write; read per access; C read restricted shape | M7 validation, M12 `apply_schedule` cascade. |
| Site logs | `api/v1/site_logs.py` | A/S write; C read restricted shape | Append-only create/read. |
| Inventory | `api/v1/inventory.py`, `services/inventory.py`, `models/inventory.py` | A/P; **S/C 403** | Immutable `stock_movements` ledger; `quantity_on_hand` denormalized; `reconcile_project_inventory`. |
| Finance (job costing) | `api/v1/finance.py`, `services/finance.py` | A/P; **S/C 403** | `budget_spent == SUM(job_costs)`; `budget_rollup`. |
| Invoicing | `api/v1/invoicing.py`, `services/invoicing.py` | A owner, P view; C issued-only restricted shape | Milestone-driven, server-derived amounts. |
| Vendors + POs | `api/v1/vendors.py`, `api/v1/purchase_orders.py`, `services/purchase_orders.py` | A/P; **S/C 403** | PO lifecycle, M8 idempotency. |
| M15 receiving | `api/v1/purchase_orders.py` (`/receive`, `/deliveries`), `services/receiving.py`, `models/delivery.py` | A/P; **S/C 403** | Append-only receipts; verified receipt is the ONLY stock/cost release path. |
| Notifications | `api/v1/notifications.py`, `services/notifications.py` | own feed | User-scoped. |
| Idempotency | `services/idempotency.py`, `api/deps.py` (`get_idempotency_guard`) | — | M8 claim ledger. |
| Audit | `middleware/audit.py` (`record_audit`), `api/v1/audit.py` | admin read | Same-transaction; append-only. |

### 2.4 Critical invariants the AI workstream must never break

- **RBAC is the source of authorization**; Google auth (M11) never grants roles.
- **Client isolation is server-enforced and test-pinned** (M6, 17 tests): health,
  inventory, finance, PO, milestone, and budget surfaces are 403 for clients;
  ARCHIVED is 404 to non-A/P.
- Money = `Numeric(14,2)`, quantity = `Numeric(12,2)`, UUID PKs, native enums.
- `stock_movements` ledger is immutable and authoritative; `quantity_on_hand` is
  derived-in-txn. `budget_spent == SUM(job_costs)`.
- Mutations commit data + audit + notification atomically; project-scoped writes
  serialize on the project row lock; no hard deletes.
- Quality gates (P4.1): ruff 2 / mypy 10 / oxlint 1 baselines must not increase;
  `git diff --check` clean; full pytest suite green.

---

## 3. Course boundary through Weekend 07 (verified Aug 14 2026)

Verified against `mayank953/Live-Class-2026` (README, `classes_summary/` 00–12,
and the Weekend 06/07 `MIddleware.ipynb` notebook imports/cells). Latest
documented class = **Class 12 (Weekend 07, 8–9 Aug)**. The repo README states
coverage is "Phase 0 through the middle of Phase 2" — LangGraph & beyond
(Phase 3) is **future**.

### 3.1 Taught concepts (foundation for the ICE Copilot)

- **Weekend 01–02 (Classes 01–04):** Python fundamentals; API calls; hand-built
  `@tool` + `TOOL_REGISTRY`; a guarded `calculator` tool (defensive tool
  building); Pydantic `BaseModel`/`Field`/`@field_validator`/nested
  models/`model_validate_json`; AI vocabulary (LLM/tokens/context window —
  **embeddings only as a concept**); anatomy of an agent (Brain+Memory+Tools);
  stateless LLMs.
- **Weekend 02 (Class 05):** tool *schemas* handed to the model, model-decides,
  multiple tool calls in one reply, the **agentic loop** (`run_agent`,
  `max_turns`), Python-list conversation memory, Streamlit chat UI.
- **Weekend 03–04 (Classes 06–08):** `create_agent(model=…, tools=…,
  system_prompt=…, checkpointer=…)`, `@tool`, `init_chat_model`, system prompts,
  `.env`/`.gitignore` key hygiene, tool-grounded anti-fabrication; LangChain
  family + harness concept; messages (`AIMessage` fields,
  `ToolMessage`+`.artifact`, streaming `AIMessageChunk`, manual history,
  `ChatPromptTemplate`); structured output intro
  (`with_structured_output`, `BaseModel` vs `TypedDict`, `ProviderStrategy` vs
  `ToolStrategy`, `model.profile`).
- **Weekend 05 (Classes 09–10):** structured-output mastery (`Union` intents,
  validation-error **self-correction vs prompt injection**); tools deep dive
  (`args_schema`, reserved names, **bind_tools ≠ run**, **`ToolRuntime`**
  (`runtime.state/context/store/stream_writer`), `InMemoryStore` cross-session
  memory, `return_direct`, **tool gating via `wrap_model_call`**), TripMate
  preview (Open-Meteo, Tavily web search, SQLite persistence).
- **Weekend 06 (Class 11):** the **middleware loop**
  (`before_agent → before_model → wrap_model_call → after_model →
  wrap_tool_call → after_agent`); `SummarizationMiddleware`; **HITL**
  (`interrupt_on`, approve/edit/reject/respond, resume via
  `Command(resume={"decisions": […]})`, checkpointer required); **memory**
  (`InMemorySaver` + `thread_id`).
- **Weekend 07 (Class 12):** `ModelCallLimit`, `ToolCallLimit` (global + per-tool),
  `ModelFallback`, `ModelRetry`, `PIIMiddleware` (built-in + **custom regex
  detector**; Aadhaar/PAN called out), `TodoListMiddleware`,
  `LLMToolSelectorMiddleware`, `ToolErrorMiddleware`, `ToolRetryMiddleware`
  (exponential backoff), `LLMToolEmulator`, plus `ContextEditingMiddleware` /
  `ClearToolUsesEdit`; guardrail-vs-middleware distinction.

### 3.2 Explicitly NOT taught through Weekend 07

RAG, embeddings as an implementation, vector databases, MCP, multi-agent /
sub-agent systems, persistent (DB-backed) checkpointing/stores beyond
`InMemorySaver`/`InMemoryStore`, evaluation frameworks, autonomous background
agents, full observability pipelines, production deployment of agents. Parked
(§15).

---

## 4. Course-concept → ICE mapping

For each taught concept: what it teaches, how we practice it in ICE, whether it
becomes product code or stays a learning experiment, and which milestone owns it.

| Course concept | What it teaches | How we practice it in ICE | Product or experiment | Milestone |
|---|---|---|---|---|
| Chat models / messages / streaming | Provider-agnostic wiring, message vocabulary, `AIMessageChunk` | ICE assistant model client + streaming to the SPA | **Product** | AI-1 |
| Prompts / harness | System prompts, grounding, anti-fabrication | `app/ai/prompts.py` ICE system prompt (identity, RBAC honesty, registered-tools-only) | **Product** | AI-1 |
| Pydantic / structured output | Validate LLM output; self-correct on validation error | ICE intent + reply-card schemas in `app/ai/models.py` | **Product** | AI-1 |
| Tools / tool calling | Declarative tools, schemas, reserved names, bind-vs-run | ICE domain tools from §7 (`@tool` + `args_schema`) | **Product** | AI-1 |
| Agents / agentic loop | Model-calls-tools-in-a-loop harness | ICE Copilot as a `create_agent` harness; multi-step analyses | **Product** | AI-1 |
| Tool gating (`wrap_model_call`) | Removing a tool from the menu beats instructing around it | Per-role tool allow-list middleware (defense-in-depth) | **Product** | AI-1 |
| `ToolRuntime` (+context/store/stream) | Tool-side access to state/context/store | Actor-context injection; stream_writer progress; (store in AI-2) | **Product** | AI-1/AI-2 |
| Tool-grounded anti-fabrication | Ground claims in tool output | Budget/inventory answers only from tool results | **Product** | AI-1 |
| Memory / checkpointing (`InMemorySaver`, `thread_id`) | Conversation memory across turns | Per-user per-session memory | **Product** | AI-2 |
| Summarization / ContextEditing | Context compression + editing | Long-session control experiments → production option | **Product/experiment** | AI-2 |
| External tools (TripMate preview) | Multi-tool + external data + synthesis | `web_search` + internal tools (cement + market price) | **Product** | AI-3 |
| `ToolRetry` + backoff | Retry transient failures | Web/API retries only (never DB validation) | **Product (scoped)** | AI-3/AI-4 |
| ModelCall/ToolCall limits | Runaway-loop and cost caps | Production cost safety | **Product** | AI-4 |
| ModelFallback / ModelRetry | Primary → fallback; provider retry | Availability resilience | **Product** | AI-4 |
| PII + custom detector | Redact/mask incl. domain formats | Email/phone redaction + ICE/India detector experiments | **Product** (PII); **experiment** (custom) | AI-4 |
| TodoList | Explicit multi-step plan | Construction-health review plan | Experiment → product candidate | AI-4 |
| ToolError | Model-safe controlled failures | Domain errors as safe actionable messages | **Product** | AI-4 |
| `LLMToolSelector` | Cheap pre-filter cuts tool-schema tokens | Dynamic selection over a large catalog | **Product** | AI-5 |
| HITL | Pause/resume an irreversible action | Mutation approval flows | **Product (mutations only)** | AI-6 |
| `LLMToolEmulator` | Fake a tool with a model | Test mutator decision paths safely | **Experiment/test** | AI-6 |
| `return_direct` | Skip rephrasing of exact text | Exact-value tools if ever needed | Product, as needed | later |
| Middleware composition/order | Order matters (advanced corner) | Lab experiments → production ordering rules | Experiment → product | AI-4 |

---

## 5. Proposed architecture

The existing monolith has no services/repositories layer and keeps business
logic in `api/v1/` routes with a thin `services/` layer. The AI module follows
that pattern: a **self-contained `app/ai/` package** (a new bounded concern,
like `finance` or `purchase_orders`), an `api/v1/assistant.py` HTTP surface, an
integrated SPA page, and an **isolated learning lab** outside the app (§13).

```
backend/app/ai/                      # NEW — the ICE Copilot bounded context
    models.py        # Pydantic: chat request/response, structured-output
                     #   schemas (intents, reply cards), tool I/O schemas
    agent_state.py   # custom AgentState: messages + `actor` + conversation
                     #   context (project scope hints) — actor injected by the
                     #   route, NEVER from the model
    prompts.py       # system-prompt builders (identity, RBAC honesty, tool-use rules)
    agent.py         # the harness: create_agent wiring, model selection,
                     #   streaming, chat-service entrypoints (invoked by the route)
    security.py      # actor-context construction + per-role tool allow-list
                     #   (defense-in-depth, see §6); every tool also self-enforces
    tools/           # domain tools — each SELF-AUTHORIZING (§6) and read-only
                     #   until AI-6 (then HITL mutators)
        __init__.py
        ice_registry.py  # the ToolRegistry the agent + allow-list both read
        projects.py      # list_projects, get_project, get_project_health
        finance.py       # get_project_budget, get_job_costs
        inventory.py     # get_project_inventory, get_project_inventory_movements
        procurement.py   # get_purchase_orders, get_purchase_order_deliveries
        field.py         # get_project_tasks, get_daily_site_logs
        billing.py       # get_billing_milestones, get_invoices
        web.py           # web_search (AI-3+, external; SSRF-safe, rate-limited)
        mutating.py      # AI-6+ (HITL-guarded; empty until then)
    middleware/      # LangChain middleware: RBAC allow-list + logging (product)
                     #   + the Lab's experiment copies
    memory.py        # (AI-2) checkpointer wiring + long-term store (experiment)
backend/app/api/v1/assistant.py      # NEW — POST /assistant/chat (stream), GET /assistant/capabilities
backend/ai_labs/                     # NEW — isolated learning-lab scripts (§13), never imported by app/

frontend/src/pages/Assistant.tsx     # NEW — the ICE Assistant page
frontend/src/components/AssistantChat.tsx   # chat panel (streaming, tool-call pills)
frontend/src/lib/assistant.ts        # api.ts companion: chat + capabilities
frontend/src/types/assistant.ts      # assistant types (or extend types/index.ts)
```

Key wiring decisions:

- **Router/prefix:** register `assistant.router` in `api/v1/router.py` under the
  existing `api_router` (same `settings.API_V1_STR` prefix). Endpoint carries
  `Depends(get_current_user)` — **always authenticated, never anonymous**.
- **Actor-context injection:** the route resolves `user` from the bearer token
  and constructs an immutable `ActorContext` (`user.id`, `role`,
  scoped project ids). This is placed in the **custom `AgentState.actor`**
  (and mirrored to `ToolRuntime.context`) by application code. Tools read
  identity from `runtime.state`/`runtime.context` — **never** from LLM
  arguments (§6). Because `ToolRuntime` params are hidden from the model's
  `.args`, the model cannot spoof identity.
- **Streaming:** reuse the model's streaming (`AIMessageChunk`) → SSE-style
  `StreamingResponse`; stream tool-call progress via `runtime.stream_writer`.
- **Frontend:** add `/assistant` to `App.tsx`, an "AI Assistant" nav item to
  `AppShell.tsx`, gate feature set by role exactly like the rest of the UI.
  Reuse Tailwind, `Loader2`, `getErrorMessage`, TanStack Query; no new UI lib.
- **Dependency surface:** the backend currently has **no LangChain/LangGraph
  dependency** and no provider keys. AI-1 introduces `langchain`,
  `langchain-openai` + a provider key via `.env` (gitignored). The learning lab
  keeps its own isolated dependency surface so experiments never force app
  requirements. **Owner decisions needed (§17).**
- **Config:** assistant settings (model ids, provider, limits, PII strategies)
  live in `app/core/config.py` under `settings`, never hard-coded.

---

## 6. Security / RBAC doctrine (revised)

1. **Deterministic per-tool authorization.** **EVERY ICE tool independently
   enforces authorization using deterministic application logic.** Each tool
   receives the authenticated actor via runtime/application context and runs the
   same `project_access` guards + role checks as the equivalent REST endpoint.
   The model is never asked "is this allowed?" — the tool decides.
2. **Tool filtering is defense-in-depth, not the boundary.** Per-role tool
   availability (middleware allow-list) removes tools from the model's menu as a
   second layer. If that middleware ever mis-filters, each remaining tool still
   re-checks authorization itself, so no tool can over-return.
3. **Identity/role is injected by runtime/application context, never accepted
   from LLM-generated arguments.** Tool `args_schema`s contain **no**
   `user_id`/`role`/actor fields; identity lives in `AgentState.actor` /
   `ToolRuntime.context` populated by the authenticated route. `ToolRuntime`
   params are invisible to the model, so spoofing is structurally impossible.
4. **Never expose `execute_sql` or arbitrary ORM/query capabilities.** No
   generic data tool of any kind (§7). Tools are explicit business/domain
   tools over the existing services.
5. **Mutating tools remain unavailable until AI-6**, and then only
   HITL-guarded, audited, idempotent, row-locked, and still self-authorizing.
6. **Clients can never obtain through AI anything the normal M6 APIs hide.**
   The client tool set is exactly the client portal surface (projects, timeline,
   site logs, issued invoices) with role-scoped shapes; health/inventory/
   finance/procurement tools are absent for clients.
7. **Prompt-hygiene + operational guardrails.** System prompt forbids
   fabrication and restricts to registered tools; tool args are Pydantic-
   validated; tool outputs are structured ICE data; PII middleware (AI-4);
   `ToolErrorMiddleware` never leaks internal exception text; endpoints are
   bearer-auth-only and rate-limited; streaming/logs scrubbed per PII rules.

---

## 7. Initial tool catalog

All tools below are **READ-ONLY**. The AI-1 slice ships 5–6 high-value tools
(bold); the rest land by AI-5. Names follow existing REST vocabulary. "Underlying
ICE" = the exact function/pattern the tool reuses. Every tool self-enforces its
own row of this table (§6).

| Tool | Purpose | Input schema | Output shape | Underlying ICE | Roles | Project access | HITL | Lands |
|---|---|---|---|---|---|---|---|---|
| **`list_projects`** | List projects visible to the user (role-scoped) | `{include_archived?: bool}` | role-scoped project summaries (C: `ProjectClientRead`-like) | `api/v1/projects.py::list_projects` | A/P (all), S/C (assigned only) | role + assignment; ARCHIVED 404 for S/C | no | **AI-1** |
| **`get_project`** | One project's detail (role-scoped) | `{project_id}` | role-scoped `ProjectRead` / `ProjectReadRestricted` / `ProjectClientRead` | `get_project_or_404` + serializer | A/P/S/C (assigned) | `assert_can_view_project` | no | **AI-1** |
| **`get_project_health`** | Computed timeline/budget/safety + reasons | `{project_id}` | health state (no money) | `services/health.py::compute_health` | A/P/S | **C 403** (`assert_not_client`); ARCHIVED 404 | no | **AI-1** |
| **`get_project_budget`** | Budget total / spent / remaining / by cost code | `{project_id}` | `budget_rollup` output | `services/finance.py::budget_rollup` | A/P | A/P (all); S/C 403 | no | **AI-1** |
| **`get_project_inventory`** | Items + on-hand + low-stock flags | `{project_id}` | item list with balances | `api/v1/inventory.py` read path | A/P | A/P (all); S/C 403 | no | **AI-1** |
| **`get_purchase_orders`** | PO list (commitments) with line totals | `{project_id}` | PO summaries (A/P shape only) | `api/v1/purchase_orders.py` list | A/P | A/P (all); S/C 403 | no | **AI-1** |
| `get_project_tasks` | Task list (schedule data) | `{project_id}` | task summaries | `api/v1/tasks.py` read | A/S, C read restricted shape | `assert_can_view_project` | no | AI-4 |
| `get_daily_site_logs` | Site log feed | `{project_id}` | log summaries (no money) | `api/v1/site_logs.py` read | A/S, C read restricted shape | `assert_can_view_project` | no | AI-4 |
| `get_job_costs` | Job-cost ledger rows | `{project_id, cost_code?}` | list of cost entries | `services/finance.py` | A/P | A/P (all); S/C 403 | no | AI-4 |
| `get_project_inventory_movements` | Immutable movement ledger for an item | `{project_id, item_id}` | movement history | `StockMovement` query | A/P | A/P (all); S/C 403 | no | AI-5 |
| `get_purchase_order_deliveries` | M15 receipt history | `{project_id, po_id}` | deliveries + line counts | M15 `deliveries` read | A/P | A/P (all); S/C 403 | no | AI-5 |
| `get_billing_milestones` | Schedule-of-values / milestone status | `{project_id}` | milestone list | `api/v1/invoicing.py` | A (write), P view | A/P; C 403 | no | AI-5 |
| `get_invoices` | Payment requests (role-scoped) | `{project_id}` | A/P full; C issued-only restricted | `api/v1/invoicing.py` read | A/P, C (issued-only) | role-scoped | no | AI-5 |
| `get_my_notifications` | Caller's own notification feed | `{}` | own feed (self-scoped) | `services/notifications.py` | all roles | self only | no | AI-1 (optional) |
| `web_search` | **External** market-price / reference lookup | `{query, region?}` | ranked text snippets + sources | SSRF-safe fetcher (Tavily-style per Class-10 TripMate) | A/P (recommended) | external only; rate/call-limited | no (read-only) | **AI-3** |
| `propose_job_cost` / `propose_po_receive` (etc.) | **Mutating** (HITL-guarded proposals) | structured proposal args | proposal → HITL approve/edit/reject | existing mutating services + audit + idempotency | A/P | A/P (all); S/C 403 | **yes** | **AI-6** |

Design rules for tools:

- Thin wrappers over existing services/route logic; **authorization is
  self-enforced per tool** (§6.1), never re-implemented ad hoc.
- Inputs validated by Pydantic `args_schema`; no free-form SQL or dict dumps.
- Money/quantity formatting server-side; model receives display strings plus
  structured fields.
- Mutating tools are `mutating: false` in the registry until AI-6.

---

## 8. External / web tool strategy

- One external **`web_search`** tool lands in **AI-3** to practice multi-tool
  reasoning (e.g. *"How much cement do we have in Project X and what is the
  current market price?"* = `get_project_inventory` + `web_search` + LLM
  synthesis with source attribution).
- Not implemented before AI-3. When it lands: SSRF-safe (allow-listed fetcher,
  no arbitrary-URL proxy), rate-limited and **tool-call-limited**
  (`ToolCallLimitMiddleware`), retried only for transient failures
  (`ToolRetryMiddleware`), PII-scrubbed query logs, results flagged
  non-authoritative ("verify before purchase").
- Roles: **admin + procurement only** in the first version.

---

## 9. Memory strategy (taught material only — no RAG, no vector DB)

1. **Conversation memory (AI-2):** `InMemorySaver` checkpointer + `thread_id`
   per (user, session) — the Class 11/06 pattern. Then custom `AgentState`
   with conversation + **project context** (the project a user is asking about),
   so the copilot remembers what it was already told.
2. **Summarization (AI-2):** `SummarizationMiddleware` with a separate cheaper
   model (Class 11) and **context-strategy experiments** (§13): no-summary vs
   summary vs context-editing; measure token growth, correctness, and drift.
3. **Long-term memory (AI-2 experiment):** `ToolRuntime.store` / `InMemoryStore`
   (Class 10) as an experiment. Production persistence via an ICE-owned
   append-only table behind a migration **only in a later milestone** — not
   AI-0/AI-1.
4. **Never** vector indexes / embeddings / RAG (not taught → §15).

---

## 10. Middleware experiments (mapped to milestones; full lab in §13)

| Middleware | ICE experiment | Learning demo | Real product behavior | Milestone |
|---|---|---|---|---|
| Per-role allow-list + logging (`wrap_model_call`) | RBAC tool menu + request tracing | VIP-gating pattern (Class 10) | **Yes — defense-in-depth** (§6.2) | AI-1 |
| SummarizationMiddleware | Long-session compression | Trigger/keep tuning | **Product option** | AI-2 |
| ContextEditing / ClearToolUsesEdit | Context strategy control | Notebook demos | Experiment | AI-2 |
| ToolRetry (+backoff) | Retry transient **web/API** calls only | `max_retries/backoff_factor/initial_delay` on a flaky web stub | **Yes — external tools only** | AI-3 |
| ModelCallLimit / ToolCallLimit | Runaway-loop + expensive-tool caps | Tiny limits + `exit_behavior="end"` | **Yes — production** | AI-4 |
| ModelFallback / ModelRetry | Primary cloud → fallback; provider retry | Bad-key forced failure | **Yes — production** | AI-4 |
| PII + custom detector | Email/phone redaction; ICE/India detector | Redact vs mask compare | **Yes (PII)**; **experiment** (custom) | AI-4 |
| TodoList | Construction health review plan | Observe plan → execute | Experiment → candidate | AI-4 |
| ToolError | Model-safe domain errors | Exception type, not text | **Yes — production** | AI-4 |
| ToolRetry deeper | Backoff timing, exception filtering | Time-elapsed proof | **Yes — scoped** | AI-4 |
| LLMToolSelector | Dynamic selection over a large catalog | `max_tools`/`always_include`; token compare | **Yes — production** | AI-5 |
| LLMToolEmulator | Fake future mutators | Emulator vs real decision paths | **Test-only** | AI-6 |
| HumanInTheLoop | Mutation approval (approve/edit/reject/respond) | Class 11 flow + resume via `Command` | **Yes — mutations only** | AI-6 |

---

## 11. HITL strategy

- Read-only tools never need HITL. HITL applies only to **mutating** assistant
  actions, which are unavailable until **AI-6**.
- Every AI-6 mutator must also satisfy the REST mutation doctrine before
  shipping: `record_audit` in-transaction, M8 idempotency (a retry can never
  double-apply), project row-lock ordering, role gates, and a **human approval**
  via `HumanInTheLoopMiddleware` (`interrupt_on`, decisions approve/edit/
  reject/respond, resumed with `Command(resume=…)` on the same `thread_id`,
  checkpointer required).
- Recommended first mutators (low-risk → sensitive, per owner): job-cost
  **proposal**, then PO-receive **proposal**. The assistant only ever proposes;
  the human confirms.
- Mutators are emulated via `LLMToolEmulator` in the lab (§13) before any real
  execution is enabled.

---

## 12. AI milestone sequence (vertical slices)

Each milestone is a substantial, useful product increment. No milestone is a
"re-teach" of a basic concept; basics are assumed known and exercised in passing,
while the focus is advanced/adjacent corners of taught concepts (official
LangChain docs allowed for those corners).

### AI-1 — Read-Only ICE Copilot Core

1. **Product capability:** an authenticated, role-aware ICE Copilot chat in the
   SPA that answers real questions about the caller's projects — health,
   budget, inventory, purchase orders — grounded in tool results, streaming to
   the UI, with hard tool-level RBAC.
2. **Learning objectives:** build a genuinely useful `create_agent` harness;
   deepen `ToolRuntime` (state/context/streaming); custom `AgentState`;
   streaming agent + tool progress; async tools; defensive tool schema design.
3. **Course concepts exercised:** chat models, messages, prompts, Pydantic,
   `create_agent`, `@tool`, tool calling, agentic loop, tool gating
   (`wrap_model_call`), role-scoped serialization (M6 parity).
4. **Advanced LangChain-doc topics intentionally explored:** `ToolRuntime`
   (`runtime.state`/`context`/`stream_writer`), custom `AgentState` schemas,
   async tool definitions, tool schema design (descriptions, `args_schema`,
   reserved names), streaming agent/tool progress, batching parallel tool calls.
5. **ICE tools/features involved:** `list_projects`, `get_project`,
   `get_project_health`, `get_project_budget`, `get_project_inventory`,
   `get_purchase_orders` (+ optional `get_my_notifications`); actor-context
   injection; per-role allow-list middleware; structured reply cards.
6. **Architecture changes:** `app/ai/` package (models/agent_state/prompts/
   agent/security/tools), `api/v1/assistant.py`, router registration,
   `requirements.txt` (+`langchain`*, `langchain-openai`), config keys, frontend
   `/assistant` page + `AssistantChat.tsx` + `lib/assistant.ts` + types.
7. **Security/RBAC rules:** §6 doctrine: deterministic per-tool authorization;
   actor injected via runtime context never via args; tool filtering as
   defense-in-depth; no SQL/ORM tools; read-only only; client tool set = M6
   surface; bearer-auth + rate-limited.
8. **Experiments to run:** tool-gating VIP pattern vs instruct-only; streaming
   TTFB; parallel tool-call batching on a multi-part question.
9. **Metrics to capture:** tokens/turn (`usage_metadata`), tool-call counts,
   latency + first-token time, per-role tool availability, correctness of
   grounded answers.
10. **Tests:** 401 unauthenticated; role matrix; client can never reach
    health/budget/inventory/PO tools; cross-project 404; ARCHIVED 404 for S/C;
    role-scoped output shapes; streaming shape; no-data-claims prompt contract.
11. **Acceptance criteria:** an authenticated user gets correct, tool-grounded,
    streamed answers for their permitted data; a client gets exactly the client
    portal surfaces; nothing mutates; quality gates green.
12. **Concepts explicitly deferred:** memory persistence (AI-2), web search
    (AI-3), limits/fallback/PII (AI-4), selector (AI-5), any mutation (AI-6).

### AI-2 — Conversation Intelligence

1. **Product capability:** the Copilot remembers and reasons across a session
   and tracks which project is being discussed, with controlled context growth.
2. **Learning objectives:** `InMemorySaver` + `thread_id`; custom `AgentState`
   fields; conversation + project context; `SummarizationMiddleware`;
   `ContextEditingMiddleware`/`ClearToolUsesEdit`; context-strategy
   comparison.
3. **Course concepts exercised:** checkpointing/memory (Class 11/06),
   summarization (Class 11), ToolRuntime store (Class 10).
4. **Advanced LangChain-doc topics intentionally explored:** custom `AgentState`
   with context fields; summarization `trigger`/`keep` tuning; context editing
   vs summarization; per-thread context isolation.
5. **ICE tools/features involved:** same read-only tools; `assistant_memories`
   (in-memory first); project-context resolution ("in Project X, …").
6. **Architecture changes:** `app/ai/memory.py`, checkpointer wiring, session/
   thread keying per (user, session), context-resolution helper; frontend
   session/thread persistence in the page.
7. **Security/RBAC rules:** memory namespaced per user; nothing cross-user; a
   remembered project context must still pass the same per-tool authorization
   each turn (memory never widens access).
8. **Experiments to run:** no-summary vs `SummarizationMiddleware` vs
   `ContextEditingMiddleware` on the same conversation; token growth over
   turns; context-switch accuracy ("now talk about the other project").
9. **Metrics to capture:** context size per turn; tokens saved; answer drift
   (n-gram/targeted Q) with/without compression; memory-hit rate.
10. **Tests:** two-turn context; thread isolation across users/sessions;
    context does not bypass RBAC; summarization output correctness.
11. **Acceptance criteria:** "earlier you said project Y" works; a project
    mentioned once is recalled later; context stays bounded on long sessions.
12. **Concepts explicitly deferred:** persistent/DB memory (later milestone),
    web search (AI-3), limits/fallback/PII (AI-4), mutations (AI-6).

### AI-3 — External Intelligence

1. **Product capability:** multi-tool reasoning across internal ICE data and
   external web data with source-aware synthesis (e.g. cement on hand + current
   market price).
2. **Learning objectives:** external tools; sequential vs parallel tool calls;
   source attribution; `ToolRetryMiddleware` on transient external calls only;
   streaming multi-tool progress.
3. **Course concepts exercised:** TripMate preview (Class 10), tools, agentic
   loop, `ToolRetry` (Class 12).
4. **Advanced LangChain-doc topics intentionally explored:** parallel vs
   sequential tool-call execution; retry semantics and exception filtering
   (retry only `ConnectionError`/timeout classes); usage/token/cost comparison
   across strategies.
5. **ICE tools/features involved:** `web_search` (+ rate/call limits) combined
   with `get_project_inventory`, `get_project_budget`, `get_purchase_orders`.
6. **Architecture changes:** `app/ai/tools/web.py` (SSRF-safe fetcher),
   settings for provider/limits, source-aware reply model, frontend source
   citations.
7. **Security/RBAC rules:** web_search A/P only; no arbitrary-URL proxy; call
   limits; PII-scrubbed query logs; external results non-authoritative; all ICE
   tools still self-authorize.
8. **Experiments to run:** sequential vs parallel tool-call ordering on a
   3-tool question; with/without retry under a flaky web stub; cost/latency
   comparison.
9. **Metrics to capture:** tool-call count and order; web latency; retry count
   + backoff delay; tokens; answer correctness + source coverage.
10. **Tests:** multi-tool synthesis; web-tool RBAC; transient retry fires only
    for external tools; no arbitrary URL fetch; non-authoritative flagging.
11. **Acceptance criteria:** the cement+price question answers from both tool
    results with cited sources and a "verify before purchase" caveat.
12. **Concepts explicitly deferred:** limits/fallback/PII (AI-4), selector
    (AI-5), mutations (AI-6).

### AI-4 — Middleware & Resilience Lab

1. **Product capability:** a resilient, bounded, PII-safe Copilot: runaway
   loops capped, provider fallback, controlled errors, safe retries.
2. **Learning objectives:** the Weekend-07 middleware set; middleware
   composition/order; model vs tool retry; exception filtering; measuring
   behavior under deliberately induced failures.
3. **Course concepts exercised:** all of Class 12 plus the Class 11 loop.
4. **Advanced LangChain-doc topics intentionally explored:** middleware
   ordering/composition semantics; `ModelRetry` vs `ToolRetry`; retry exception
   filtering; `PIIMiddleware` strategies redact vs mask + custom detectors;
   limit `exit_behavior`.
5. **ICE tools/features involved:** full read-only catalog; `web_search`
   (external) already in place for retry/limit experiments.
6. **Architecture changes:** production middleware wiring in `app/ai/agent.py`;
   settings for limits/fallback/PII; error-mapping for ICE domain errors.
7. **Security/RBAC rules:** PII redaction before model call; limits bound cost;
   internal exception text never reaches the model; RBAC doctrine unchanged.
8. **Experiments to run (§13):** induced-failure matrix (bad key, rate limit,
   malformed input, flaky tool); middleware ordering permutations; redact vs
   mask; fallback trigger; TodoList multi-step plan.
9. **Metrics to capture:** cost under induced failures; recovery rate; PII
   detection/redaction coverage; limit-trigger counts; error-type-not-text
   compliance.
10. **Tests:** each middleware trigger; fallback fire; PII redaction/mask;
    backoff timing; DB-validation errors never retried; error text never leaks.
11. **Acceptance criteria:** a runaway loop is capped; failed primary falls
    back; PII redacted; domain errors surface safely; cost bounded.
12. **Concepts explicitly deferred:** selector (AI-5), mutations/HITL (AI-6).

### AI-5 — Dynamic Tool Architecture

1. **Product capability:** a large, organized ICE tool catalog served
   efficiently via dynamic selection, with measurable token/cost/latency
   savings.
2. **Learning objectives:** `LLMToolSelectorMiddleware`; `max_tools` /
   `always_include` strategy; tool taxonomy/domain organization; measurement.
3. **Course concepts exercised:** tool gating, dynamic selection (Class 12).
4. **Advanced LangChain-doc topics intentionally explored:** selector-model
   token accounting; compare with/without selector on cost, latency,
   correctness; tool schema design at scale.
5. **ICE tools/features involved:** full §7 catalog (inventory movements, PO
   deliveries, milestones, invoices) organized by domain module.
6. **Architecture changes:** tool taxonomy/registry maturity; selector wiring +
   per-role always-include (e.g. `list_projects`); metrics endpoint/logging.
7. **Security/RBAC rules:** the selector only narrows the RBAC allow-list,
   never widens it; per-role `always_include`; doctrine unchanged.
8. **Experiments to run:** selector on/off over a mixed question set; token and
   latency deltas; correctness regressions.
9. **Metrics to capture:** main-model input tokens with/without selector;
   selector tokens; cost; latency; answer correctness.
10. **Tests:** selector keeps `always_include` tools; never exposes a tool the
    role lacks; correctness parity with no-selector baseline.
11. **Acceptance criteria:** token cost drops measurably at equal or better
    correctness; catalog is cleanly organized by domain.
12. **Concepts explicitly deferred:** mutations/HITL (AI-6); untaught families
    (§15).

### AI-6 — Controlled Agent Actions

1. **Product capability:** the Copilot proposes low-risk ICE actions and can
   execute them only with explicit human approval, fully audited.
2. **Learning objectives:** HITL decision flows (approve/edit/reject/respond);
   resume via `Command` on the same thread; `LLMToolEmulator`; progressive
   trust from low-risk to sensitive operations.
3. **Course concepts exercised:** HITL (Class 11), `LLMToolEmulator` (Class 12).
4. **Advanced LangChain-doc topics intentionally explored:** HITL decision
   flows and edit payloads; emulator-vs-real parity; checkpointer-required
   resume; streaming mutation progress.
5. **ICE tools/features involved:** first **mutating** tools — e.g.
   `propose_job_cost`, `propose_po_receive` — gated behind HITL, audit,
   idempotency, row locks, and role gates.
6. **Architecture changes:** `app/ai/tools/mutating.py`, HITL middleware +
   checkpointer, frontend approval UI (approve/edit/reject/respond), audit hook.
7. **Security/RBAC rules:** §6.5 — mutations only in AI-6+; hard RBAC inside
   every tool; every action uses `record_audit` + M8 idempotency + project row
   locks; HITL is the gate, never a bypass.
8. **Experiments to run (§13):** emulator first, then HITL flows; decision
   distribution; edit-payload path; replay/idempotency under HITL.
9. **Metrics to capture:** proposal→approval/rejection rates; edit frequency;
   audit coverage; idempotent-replay correctness; time-to-approve.
10. **Tests:** all four HITL decisions; resume on same thread; audit row; M8
    replay single-apply; RBAC on every mutator; rollback on reject.
11. **Acceptance criteria:** a proposal cannot commit without human approval;
    every executed action is audited and idempotent; low-risk tools ship before
    sensitive ones.
12. **Concepts explicitly deferred:** all untaught families (§15); anything
    beyond HITL-guarded proposals.

---

## 13. Learning experiments & the learning lab

**Lab location (decision): `backend/ai_labs/`** — plain-Python experiment
scripts, one directory per experiment family, each self-contained with its own
`pyproject.toml`/dependencies (never imported by `app/`). This fits the repo
better than `backend/notebooks/ai/`: the repository has **no Python notebook
workflow** (all `.ipynb` files live in `docs/` for documentation), CI runs
`.py`-only gates, and dev harnesses already live in `backend/scripts/` — but a
dedicated `ai_labs/` keeps experiments clearly outside the app import path and
separate from M-series smoke harnesses. A `backend/ai_labs/README.md` explains
each experiment, its env vars, and how to run it.

**Experiments (each = one script/notebook-style `.py` + a notes cell/markdown):**

1. **ProviderStrategy vs ToolStrategy** — same ICE structured-output task via
   `ProviderStrategy` and `ToolStrategy`; compare reliability, latency, and
   tokens; validate the known ToolStrategy+real-tools caveat on our models.
2. **Sequential vs parallel tool calling** — a 3-tool ICE question executed
   sequentially vs batched; measure latency, correctness, and tool-error
   interplay.
3. **With/without ToolSelector** — token/cost/latency/correctness comparison
   over a mixed question set (feeds AI-5).
4. **Model retry vs tool retry** — induced provider error vs tool error; which
   middleware should catch which; exception filtering.
5. **Retry backoff timing** — reproduce `delay = initial_delay * backoff_factor
   ** retry_number` and print real elapsed time between attempts.
6. **Middleware ordering** — permutations of the Class-12 set; observe
   behavior changes (feeds AI-4 production ordering rules).
7. **PII redact vs mask** — same input with `redact` vs `mask`; what the model
   sees; custom ICE/India detector behavior.
8. **Fallback behavior** — force primary failure (bad key); verify fallback
   fires and confirm the user-facing symptom is avoided.
9. **Context growth with/without summarization** — long-conversation token
   curve and answer drift (feeds AI-2).
10. **LLMToolEmulator vs real tool** — same decision path with an emulated vs
    real tool; verify emulator never executes side effects.
11. **HITL approve/edit/reject/respond** — full interactive flow on a mock
    mutating tool; verify resume via `Command` on the same thread.

Each experiment records: hypothesis, setup, observed metrics, and a
**LEARNING DEMONSTRATION vs REAL PRODUCT BEHAVIOR** conclusion (§14).

---

## 14. Learning-vs-production distinction (summary)

- **Product (production) from the start:** authenticated chat surface, model
  layer, prompts, structured-output schemas, read-only domain tools, per-role
  allow-list gate, actor-context injection, rate limits, cost/loop caps,
  fallback, PII (email/phone), controlled tool errors, web-search limits +
  retry (AI-3/AI-4), HITL for mutations (AI-6), audit/idempotency for any
  mutator.
- **Learning experiments (non-shipping):** everything in `backend/ai_labs/` —
  ProviderStrategy/ToolStrategy comparisons, parallel/sequential tool calling,
  selector cost studies, retry/backoff timing, middleware ordering, PII
  redact-vs-mask, custom detectors, emulator-vs-real, HITL flow demos. These
  are isolated, never imported by `app/`, and can be replayed against the
  course notebooks.
- Rule of thumb: **if it can return wrong data, leak data, mutate data, or
  cost unbounded money, it is production-guarded. If it only demonstrates a
  course mechanism, it lives in the lab as an experiment.**

---

## 15. Future-course parking lot (NOT YET TAUGHT — deferred until covered)

> **DEFERRED UNTIL COURSE COVERS THIS.** No design work here; only placement.

- **RAG** (retrieval-augmented generation) — Phase 3 of the course.
- **Embeddings** (implementation; Class 03 covers only the vocabulary).
- **Vector databases / vector stores.**
- **MCP** (Model Context Protocol).
- **Multi-agent / sub-agent systems** (Deep Agents only *mentioned*).
- **Advanced persistent memory** beyond `InMemorySaver`/`InMemoryStore`
  (DB-backed checkpointing/stores; durable execution).
- **Evaluation frameworks / evals** (LangSmith as a platform is introduced in
  Class 07 but evals are not exercised).
- **Observability/tracing pipelines** beyond LangSmith trace mention.
- **Autonomous background agents / scheduled agents.**
- **Production deployment of agents** (cloud/VPS capstone, Phase 4 of the
  course).
- **ICE-specific later material:** Phase 6 photo/voice data, Phase 7 predictive
  delay / CV-QC / BOQ AI (ICE roadmap's original AI/ML features) — gated on ICE
  Phase 4–7 rails AND on the course reaching the relevant concepts.

When a concept moves from this list to §3.1 (because a new weekend covers it),
re-run the AI-0 process for that slice (§16).

---

## 16. Process for incorporating Weekend 08+

1. When a new `Weekend NN` folder lands in `mayank953/Live-Class-2026`, read its
   `classes_summary` entry + notebook, and update §3.1/§3.2 and the matrix.
2. For each newly taught concept, produce the same mapping record used here
   (what it teaches → ICE practice → product vs experiment → milestone).
3. Decide whether to **extend an existing milestone or add AI-7+** (prefer new
   small milestones over bloating existing ones).
4. Update §7 (new tools only if required, still read-only-first, still
   self-authorizing), §10/§13 (new middleware experiments), §15 (move the
   concept out of the parking lot), and the milestone sequence.
5. Get owner approval on the delta before implementing (no major implementation
   without approval; no commit/push unless asked).

---

## 17. Recommended AI-1 implementation plan

Scope for the next approved milestone — a genuinely useful read-only ICE
Copilot core:

1. **Owner decisions to confirm:** (a) primary LLM provider/model (OpenAI
   recommended for course parity; Groq/OpenRouter free options exist), (b) add
   LangChain now (recommended — the product path) vs a throwaway pure-Python
   loop in the lab first (optional learning step, not the product path), (c)
   assistant rate-limit budget, (d) whether `get_my_notifications` ships in
   AI-1 (recommended: yes — cheap, self-scoped) — final AI-1 tool set = the six
   bold tools in §7 (+ notifications if approved).
2. **Dependencies/config:** add `langchain`, `langchain-openai` (+ provider
   SDK) to `requirements.txt`; provider key via `.env` (gitignored); assistant
   settings in `app/core/config.py`.
3. **Backend:** `app/ai/agent_state.py` (custom `AgentState` with `actor`
   injected by the route), `app/ai/models.py` (chat + structured reply
   schemas), `app/ai/prompts.py` (ICE system prompt), `app/ai/security.py`
   (actor-context + per-role allow-list), `app/ai/tools/` (the six tools,
   each self-authorizing), `app/ai/agent.py` (streaming `create_agent`
   harness), `app/api/v1/assistant.py` (`POST /assistant/chat` stream,
   `GET /assistant/capabilities`), router registration.
4. **Frontend:** `/assistant` route + nav item; `AssistantChat.tsx` (streaming,
   tool-call pills, structured reply cards); `lib/assistant.ts`; types; role
   gating consistent with the rest of the UI.
5. **Tests:** `backend/tests/test_assistant.py` — 401 unauthenticated; role
   matrix (client never reaches health/budget/inventory/PO); cross-project 404;
   ARCHIVED 404 for S/C; role-scoped output shapes; streaming shape; no-data-
   claims prompt contract; rate limit.
6. **Non-goals for AI-1:** memory persistence, summarization, web search,
   limits/fallback/PII middleware, tool selector, any mutation, any migration.
7. **Acceptance:** an authenticated user can hold a streamed, tool-grounded
   conversation over their permitted data; clients see only M6 surfaces;
   nothing mutates; quality gates green; existing M15 work untouched.

---

## Compact matrix — Course Concept | ICE Exercise | Product Value | Milestone | Status

| Course concept | ICE exercise | Product value | Milestone | Status |
|---|---|---|---|---|
| Chat models / messages | ICE chat surface, streaming | In-product copilot | AI-1 | planned |
| Prompts / harness | ICE system prompt, grounding | Trustworthy answers | AI-1 | planned |
| Pydantic / structured output | ICE intents + reply cards | Machine-readable output | AI-1 | planned |
| Tools / tool calling | Read-only domain tools | Copilot reads real data | AI-1 | planned |
| Agents / agentic loop | Multi-step analysis | Real multi-step answers | AI-1 | planned |
| Tool gating (`wrap_model_call`) | Per-role allow-list | RBAC defense-in-depth | AI-1 | planned |
| `ToolRuntime` + custom `AgentState` | Actor injection + tool-side context | Safe identity plumbing | AI-1/AI-2 | planned |
| Memory / checkpointing | Per-user session memory | Context across turns | AI-2 | planned |
| Summarization / ContextEditing | Context-strategy lab | Cost/context control | AI-2 | planned |
| Web search (TripMate preview) | Market-price + inventory reasoning | Procurement insight | AI-3 | planned |
| ToolRetry + backoff | Web-tool retries only | Resilience for external calls | AI-3/AI-4 | planned |
| ModelCall / ToolCall limits | Runaway-loop + cost caps | Cost safety | AI-4 | planned |
| ModelFallback / ModelRetry | Primary→fallback | Availability | AI-4 | planned |
| PII + custom detector | Email/phone + India/ICE IDs | Compliance; log hygiene | AI-4 | planned |
| TodoList | Construction health review plan | Stepwise analysis | AI-4 | experiment |
| ToolError | Model-safe domain errors | No stack leaks | AI-4 | planned |
| ToolSelector | Dynamic selection over large catalog | Token/cost reduction | AI-5 | planned |
| HITL | Mutation approval flows | Safe assistant mutations | AI-6 | planned |
| LLMToolEmulator | Fake future mutators | Safe testing | AI-6 | experiment |
| RAG / embeddings / vector DB / MCP / multi-agent | — (parking lot) | — | deferred | not taught |
