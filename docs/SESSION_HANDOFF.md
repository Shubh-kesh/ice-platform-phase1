# ICE Platform — Session Handoff

Current working-session handoff. **Not** a historical document — describes the
**currently verified** repository state so a completely fresh OpenCode session
can continue without this conversation's context. Facts were re-verified on
Aug 15, 2026; trust code/tests over any stale wording here.

## 1. Handoff Status

- **Date:** Aug 15, 2026 (session).
- **Branch:** `claude-development`; **HEAD:** `9bfe711` (feat: implement M15
  purchase order receiving), **ahead of `origin/claude-development` by 1**
  (M15 is committed but **not pushed**).
- **Committed + pushed:** M14 (`e8735d7`), M13 (`3315957`), M6 close-out
  (`7795890`), P4.1 (`99bf282`), and all prior milestones.
- **Working tree (uncommitted):**
  - **AI-1 — ICE Copilot (COMPLETE, verified, not committed):** backend
    `app/ai/` + `api/v1/assistant.py`; tests (`test_assistant.py`,
    `test_agent_loop.py`, `test_assistant_api.py`, `fakes.py`); frontend
    `/assistant` page (`pages/Assistant.tsx`, `components/AssistantChat.tsx`,
    `lib/assistant.ts`, `types/assistant.ts`, `App.tsx` route, `AppShell` nav,
    `lib/api.ts` exports); config/settings + rate limit + requirements
    (LangChain/LangGraph pins); `backend/ai_labs/`; docs
    (`AI_ASSISTANT_ROADMAP.md`, `AI1_IMPLEMENTATION_PLAN.md`,
    `AI1_IMPLEMENTATION_SUMMARY.md`, `AI1_IMPLEMENTATION_REVIEW.md`).
  - **M15 is committed** (at HEAD `9bfe711`); the working-tree M15 edits are
    therefore already in HEAD. The AI-1 work is the only uncommitted change set.
- **Database:** repo Alembic head **`l5d6e7f8a9b0`** (M15); live dev DB
  verified at the same revision (Docker up, `ice-platform-*` healthy).
- **Environments running:** Docker backend (`:8000`, healthy) + Vite dev server
  (`:5173`). Host test env aligned to the pinned requirements (pydantic 2.9.2,
  langgraph 1.2.11 family).

## 2. Current Project State

- **Completed milestones (committed):** Phase 1, Phase 2, M1–M14, P4.1, and
  **M15 — PO delivery verification/receiving** (HEAD `9bfe711`, not pushed).
- **AI workstream — AI-1 (ICE Copilot) COMPLETE and verified SAFE TO COMMIT**
  (uncommitted): backend 390 passing (56 AI), frontend build PASS,
  oxlint/ruff/mypy delta gates PASS, real-provider + Docker-DB + client
  prompt-injection smokes PASS. Canonical docs:
  `docs/AI1_IMPLEMENTATION_REVIEW.md` (technical) and
  `docs/AI1_IMPLEMENTATION_SUMMARY.md` (plain-language).
- **Next AI milestone: AI-2 — Conversation Intelligence** (memory/checkpointing,
  conversation context, summarization) — NOT started.
- **M-series development remains paused** (owner-directed; Phase 5 next after
  M15 would be M16, but it is on hold while the AI workstream runs).
- **Alembic head = `l5d6e7f8a9b0`** (M15); chain-tested.
- **Backend tests:** **390 passing** (verified Aug 15, 2026), incl. 56 AI
  tests (assistant tools, agent loop, SSE API, provider factory, execution logging).
- **Frontend:** `npm run build` (tsc + vite) passes; oxlint delta gate PASS
  (1 pre-existing `auth-context.tsx` Fast-Refresh warning).
- **Quality gates:** ruff 2 / mypy 10 / oxlint 1 baselines met (`ci_quality.py`
  delta PASS); `git diff --check` clean.
- **Deployment/demo:** Docker Compose + Vite (both up); Render.com documented
  demo target; Phase 4 production rails deferred (P4.1 CI/CD only done).

## 3. Committed Work (recent)

| Commit | What |
|---|---|
| `9bfe711` | **feat: implement M15 purchase order receiving** — receiving routes/service, `po_receive` audit + notifications, cancel guard, `test_receiving.py`, frontend receive UI. **Not pushed (ahead 1).** |
| `e8735d7` | **feat: add vendors and purchase orders (M14)** — pushed. |
| `36f166d` | **docs: add milestone plans and infrastructure decisions** — pushed. |
| `13677fd` | **docs: add durable AI session context** — pushed. |
| `7795890` | **test: close out client portal security boundary (M6)** — pushed. |
| `3315957` | **feat: add in-app notifications and alerts (M13)** — pushed. |

No AI-1 commit exists yet (owner will instruct commit after this handoff).

## 4. Current Worktree State (uncommitted — AI-1)

- **Backend new:** `backend/app/ai/` (`__init__`, `context`, `security`,
  `models`, `prompts`, `agent`, `logging`, `tools/*`), `backend/app/api/v1/
  assistant.py`, `backend/tests/{fakes.py,test_assistant.py,test_agent_loop.py,
  test_assistant_api.py,test_assistant_logging.py}`, `backend/.env.example`,
  `backend/ai_labs/`.
- **Backend modified:** `api/v1/router.py` (assistant router),
  `core/config.py` (ICE_AI_* settings), `core/rate_limit.py`
  (`ASSISTANT_RATE_LIMIT=10/minute`), `requirements.txt` (LangChain/LangGraph
  family pins), `.ci/baseline_mypy.txt` (re-baselined 5 pre-existing
  `config.py` errors at line 111 — shifted by the added settings, documented).
- **Frontend new:** `pages/Assistant.tsx`, `components/AssistantChat.tsx`,
  `lib/assistant.ts`, `types/assistant.ts`.
- **Frontend modified:** `App.tsx` (`/assistant` route), `AppShell.tsx` (nav
  item), `lib/api.ts` (export `API_URL`, `getAccessToken`).
- **Docs:** `docs/AI_ASSISTANT_ROADMAP.md`, `docs/AI1_IMPLEMENTATION_PLAN.md`,
  `docs/AI1_IMPLEMENTATION_SUMMARY.md`, `docs/AI1_IMPLEMENTATION_REVIEW.md`
  (all new), plus `docs/AI_CONTEXT.md`, `docs/SESSION_HANDOFF.md`,
  `docs/CURRENT_STATE.md`, `docs/ROADMAP.md` regenerated to the AI-1-complete
  state (this reconciliation session).
- No migrations beyond `l5d6e7f8a9b0`; no application-behavior changes outside
  the AI module + its router/config/requirements.

## 5. AI-1 Implementation State (canonical: `docs/AI1_IMPLEMENTATION_REVIEW.md`)

- **Complete and verified.** 7 read-only ICE tools; `ActorContext` +
  `ToolRuntime` identity injection; hard per-tool RBAC + role-filtered catalog;
  M6 client isolation; multi-provider model factory (openai / anthropic / groq
  / openrouter via ChatOpenAI+base_url); `POST /assistant/chat` SSE streaming;
  `GET /assistant/capabilities`; React `/assistant` Copilot UI; 10/min rate
  limit; usage metrics.
- **Verified:** backend 390 (56 AI), frontend build + oxlint, ruff/mypy/oxlint
  delta gates, real-provider smoke (openrouter /
  `nvidia/nemotron-3-super-120b-a12b:free`, grounded + SSE correct), real
  Docker-DB smoke, client prompt-injection smoke (no budget leak), no mutation,
  no migration.
- **Pinned AI dependency family:** langchain 1.3.15 · langchain-core 1.5.5 ·
  langchain-openai 1.5.1 · langchain-anthropic 1.5.6 · langchain-groq 1.1.3 ·
  langgraph 1.2.11 · langgraph-prebuilt 1.1.0 · langgraph-checkpoint 4.2.0 ·
  langgraph-sdk 0.4.2 · openai 2.54.0 (httpx 0.27.2, pydantic 2.9.2 unchanged).
- **AI-1 limitations (deliberate):** stateless (no memory), read-only (no
  mutators), no web search, no middleware (limits/fallback/PII/retry), no RAG/
  vector/MCP/multi-agent.

## 6. Deferred Work

- **AI-2 — Conversation Intelligence** (next AI milestone): InMemorySaver +
  thread_id, conversation/project context, summarization, context editing.
- **AI-3 … AI-6** per `docs/AI_ASSISTANT_ROADMAP.md` (web search, middleware,
  tool selector, HITL/mutations).
- **Phase 4 P4.2–P4.6** (production infrastructure) — blocked on owner D1–D9.
- **M16+ (multi-location inventory, 7-day forecast)** — Phase 5 remainder,
  paused while the AI workstream runs.
- **Email/SMS/push delivery**, httpOnly refresh cookies, frontend automated
  tests, Phase 6/7/8 — planned, not started.

## 7. Unresolved Owner Decisions

- **P4.2 D1–D9** (provider/IaC/DB/Redis/secrets/domain/backup/IAM/staging).
- **Email/push notification delivery** (provider + secrets).
- **Whether to commit + push AI-1 now** (recommended next step), then start AI-2.
- **Whether to push M15** (`9bfe711` is ahead 1).
- AI provider/model preference for AI-2 onward (currently
  openrouter / `nvidia/nemotron-3-super-120b-a12b:free`).

## 8. Important Architectural Decisions (do not accidentally reverse)

- **Phase 4 production infrastructure is deferred** (P4.1 only done).
- **Dev-workflow gotcha:** compose bind-mounts only `backend/app`; `alembic/
  versions` is baked into the image — **rebuild the backend image after every
  migration change** (`docker compose build backend && docker compose up -d
  backend`). Requirements changes also need an image rebuild.
- **M14/M15 PO + receiving doctrine:** verified receipt is the ONLY path that
  releases PO quantity into inventory/costs; receipts append-only; partial
  receiving; over-receiving rejected (400).
- **AI Copilot security invariants (authoritative):** identity injected via
  `ToolRuntime.context` using the PUBLIC LangChain v1 API
  (`context_schema=ActorContext` + `context=actor` + `ToolRuntime[ActorContext]`),
  never model args; every tool self-authorizes via the REST-equivalent rules;
  role-filtered tool catalog is defense-in-depth; client tool set == M6 client
  portal set; no `execute_sql`/generic DB tool; read-only only;
  provider/model/base_url/keys are server-controlled.
- **AI execution logging:** structured `event=... request_id=...` lines on the
  `ice.ai` logger (`app/ai/logging.py`); NORMAL vs DEBUG (`ICE_AI_DEBUG=true`);
  sanitized (no secrets/identity args/raw results/chain-of-thought); no
  per-token flood. A sample trace is in `docs/AI1_IMPLEMENTATION_SUMMARY.md`.
- **AI dependency family is pinned** (langgraph 1.2.11 etc.) — host and Docker
  must resolve to the same set; do not upgrade casually (version-sensitive:
  ToolRuntime, `CONFIG_KEY_RUNTIME`, `stream_mode=["messages","updates"]`).
- **M6 client boundary**, **M9 session architecture**, **M11 Google auth**,
  **migration discipline** remain authoritative.
- Frontend dev server may be running on `:5173`; backend on `:8000`.

## 9. Known Risks / Technical Debt (top items)

- AI-1 + M15 uncommitted (M15 ahead 1 of origin) — push decisions pending.
- Production/deployment rails deferred; refresh token in `localStorage`;
  in-memory per-process rate limiting (incl. the assistant 10/min/IP).
- Baseline tooling debt (must not increase): ruff 2, mypy 10, oxlint 1.
- AI: stateless (no memory); free-model latency high (~20s); provider quality
  varies; no frontend automated tests.
- Non-blocking: sync `httpx` in async Google handlers; admin self/last-admin
  lockout; audit-list index; two uniqueness stubs; M14 PO idempotency
  finalizer duplication.
- Full details: `docs/CURRENT_STATE.md` §5–§9, `docs/AI1_IMPLEMENTATION_REVIEW.md`.

## 10. Source of Truth

- `docs/AI_CONTEXT.md` = bootstrap/navigation (regenerated this session).
- `docs/CURRENT_STATE.md` = current verified project state.
- `docs/ARCHITECTURE.md` = architecture/invariants (older; predates M10–M15 +
  AI-1 — verify endpoint surfaces in code).
- `docs/ROADMAP.md` = ICE product future direction (+ AI workstream pointer).
- `docs/AI_ASSISTANT_ROADMAP.md` = **canonical AI workstream roadmap** (AI-0
  architecture/course mapping).
- `docs/AI1_IMPLEMENTATION_PLAN.md` = approved AI-1 plan (pre-implementation).
- `docs/AI1_IMPLEMENTATION_REVIEW.md` = **AI-1 technical canonical record**.
- `docs/AI1_IMPLEMENTATION_SUMMARY.md` = **AI-1 plain-language learning summary**.
- Milestone `*_IMPLEMENTATION_PLAN/REVIEW.md` = M-series scope/verification.
- Code and tests are the ground truth; any doc conflict resolves in their favor.
