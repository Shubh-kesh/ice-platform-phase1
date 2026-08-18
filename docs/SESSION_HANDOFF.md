# ICE Platform — Session Handoff

Current working-session handoff. **Not** a historical document — describes the
**currently verified** repository state so a completely fresh OpenCode session
can continue without this conversation's context. Facts re-verified Aug 18,
2026; trust code/tests over any stale wording here.

## 1. Handoff Status

- **Date:** Aug 18, 2026 (session).
- **Branch:** `claude-development`; **HEAD:** `ce88b1f` (new developer
  directory code push); **in sync with `origin/claude-development`**; working
  tree clean.
- **AI learning workstream: Weekend 01–07 COMPLETE and committed** at
  `ce88b1f` (W7.1 memory/context, W7.2 web/retry, W7.3 middleware/resilience,
  W7.4 HITL/actions). AI-1 foundation committed earlier at `f7da04d`.
- **No AI milestone is currently in flight.** The course
  (`mayank953/Live-Class-2026`) currently ends at **Weekend 07 / Class 12**;
  no Weekend 08+ material exists. Next AI work waits for user/course Weekend
  08+.
- **Database:** repo Alembic head **`l5d6e7f8a9b0`** (M15); live dev DB
  verified at the same revision (Docker up, `ice-platform-*` healthy). AI work
  added **no migrations**.
- **Environments:** Docker backend (`:8000`) + Vite dev server (`:5173`).
  Tests run in a pinned `requirements-dev.txt` venv (fastapi 0.115.0, starlette
  0.38.6, langgraph 1.2.11 family) or the Docker image. **The host conda base
  env is drifted/broken** (fastapi 0.116 / starlette 1.6 break on import) — do
  not run tests there.

## 2. Current Project State

- **Completed milestones (all committed):** Phase 1, Phase 2, M1–M15, P4.1,
  AI-1, and the full AI learning workstream through Weekend 07.
- **AI workstream — Weekend 01–07 COMPLETE and verified SAFE.** Backend 462
  passing (128 AI), frontend build PASS, oxlint/ruff/mypy delta gates PASS, all
  20 `ai_labs/` demos run clean, secret scan clean. Canonical record:
  `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md`; plain-language:
  `docs/AI_W7_IMPLEMENTATION_SUMMARY.md`.
- **W7.4 double-resume safety is now test-pinned:** replaying the same HITL
  approval on the same thread returns `no_pending_approval` and never
  duplicates the mutation or its audit row (`tests/test_hitl.py`).
- **M-series development remains paused** (owner-directed; Phase 5 next after
  M15 would be M16, but it is on hold while the AI workstream runs).
- **Frontend:** `npm run build` (tsc + vite) passes; oxlint delta gate PASS
  (1 pre-existing `auth-context.tsx` Fast-Refresh warning).
- **Quality gates:** ruff 2=2 PASS; mypy 10=10 PASS (no new findings; 2
  baseline entries are jose/passlib stub warnings that resolve only if the
  stub packages are installed — CI does not install them); oxlint 1=1 PASS;
  `git diff --check` clean; secret scan clean.

## 3. Committed Work (recent)

| Commit | What |
|---|---|
| `ce88b1f` | **new developer directory code push** — the full Weekend 01–07 AI learning workstream (W7.1–W7.4 code, tests, `ai_labs/`, reviews) + M14/M15 + everything prior. |
| `f7da04d` | **feat: add read-only ICE Copilot (AI-1)** — foundation of the AI workstream. |
| `9bfe711` | **feat: implement M15 purchase order receiving** — receiving routes/service, `po_receive` audit + notifications, `test_receiving.py`, frontend receive UI. |
| `e8735d7` | **feat: add vendors and purchase orders (M14)** |
| `36f166d` | **docs: add milestone plans and infrastructure decisions** |
| `13677fd` | **docs: add durable AI session context** |

## 4. AI Workstream State (canonical: `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md`)

- **Weekend-07 program COMPLETE:** W7.1 memory/context · W7.2 web/retry ·
  W7.3 middleware/resilience · W7.4 HITL/actions all implemented, measured,
  and security-reviewed.
- **Tool catalog (17):** 15 read-only + `web_search` + 2 mutating
  (`create_task`, `create_daily_site_log`, HITL-guarded, default OFF). Every
  tool self-authorizes from `ToolRuntime.context`.
- **Middleware stack:** PII (input) → memory → ModelCallLimit → ModelRetry →
  ModelFallback → ToolSelector → ToolCallLimit (global + web) → ToolRetry
  (web).
- **Memory/thread model:** user-namespaced threads
  (`{user_id}::{thread_id}`) on the process-local InMemorySaver;
  summarization/context-edit modes; cross-user thread access structurally
  impossible.
- **Web/retry model:** `web_search` (Tavily via httpx) is admin/procurement
  only, results bounded + flagged non-authoritative, retried only for
  transient external failures (never DB/RBAC errors).
- **Logging model:** `ice.ai` structured events (`event=... request_id=...`);
  NORMAL vs DEBUG (`ICE_AI_DEBUG`); sanitized — no secrets/identities/raw
  results/chain-of-thought.
- **Backend tests: 462 passing (128 AI)** — verified Aug 18, 2026.
- **Frontend:** Copilot UI with conversation memory + thread list, web-search
  flag, approval card (Approve/Edit/Reject with editable fields).
- **Pinned AI dependency family:** langchain 1.3.15 · langchain-core 1.5.5 ·
  langchain-openai 1.5.1 · langchain-anthropic 1.5.6 · langchain-groq 1.1.3 ·
  langgraph 1.2.11 · langgraph-prebuilt 1.1.0 · langgraph-checkpoint 4.2.0 ·
  langgraph-sdk 0.4.2 · openai 2.54.0 (httpx 0.27.2, pydantic 2.9.2, fastapi
  0.115.0).

## 5. Deferred Work

- **Weekend 08+ AI concepts** (RAG/embeddings/vector DB, MCP, multi-agent/
  sub-agents, autonomous/background agents, advanced semantic long-term
  memory, durable threads/approvals, live selector cost benchmark) — **wait
  for the course material**; do not invent a new AI milestone.
- **Phase 4 P4.2–P4.6** (production infrastructure) — blocked on owner D1–D9.
- **M16+ (multi-location inventory, 7-day forecast)** — Phase 5 remainder,
  paused while the AI workstream runs.
- **Email/SMS/push delivery**, httpOnly refresh cookies, frontend automated
  tests, Phase 6/7/8 — planned, not started.

## 6. Unresolved Owner Decisions

- **P4.2 D1–D9** (provider/IaC/DB/Redis/secrets/domain/backup/IAM/staging).
- **Email/push notification delivery** (provider + secrets).
- **When to resume M-series development** (next product milestone would be M16).
- **What to do when Weekend 08+ course material is released** (the AI
  workstream resumes then).

## 7. Important Architectural Decisions (do not accidentally reverse)

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
  portal set; no `execute_sql`/generic DB tool; provider/model/base_url/keys
  are server-controlled; thread ownership user-namespaced; **HITL approvals are
  single-use** (double-resume → `no_pending_approval`, no duplicate
  mutation/audit, regression-pinned); mutations default OFF.
- **AI execution logging:** structured `event=... request_id=...` lines on the
  `ice.ai` logger; sanitized; no per-token flood.
- **AI dependency family is pinned** — host and Docker must resolve to the
  same set; do not upgrade casually (version-sensitive: ToolRuntime,
  `CONFIG_KEY_RUNTIME`, `stream_mode=["messages","updates"]`, HITL interrupt
  shape, ToolCallLimit thread-limit gotcha).
- **M6 client boundary**, **M9 session architecture**, **M11 Google auth**,
  **migration discipline** remain authoritative.

## 8. Known Risks / Technical Debt (top items)

- AI thread memory + pending HITL approvals are process-local (InMemorySaver):
  a backend restart loses conversation memory and pending approvals (documented
  W7.1/W7.4 limitation; durable threads are Weekend-08+).
- Production/deployment rails deferred; refresh token in `localStorage`;
  in-memory per-process rate limiting (incl. the assistant 10/min/IP).
- Baseline tooling debt (must not increase): ruff 2, mypy 10, oxlint 1.
- Free-model latency/quality varies; no frontend automated tests.
- Non-blocking: sync `httpx` in async Google handlers; admin self/last-admin
  lockout; audit-list index; two uniqueness stubs.
- Full details: `docs/CURRENT_STATE.md` §5–§9, `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md`.

## 9. Source of Truth

- `docs/AI_CONTEXT.md` = bootstrap/navigation (regenerated Aug 18, 2026).
- `docs/CURRENT_STATE.md` = current verified project state.
- `docs/ARCHITECTURE.md` = architecture/invariants (older; predates M10–M15 +
  AI — verify endpoint surfaces in code).
- `docs/ROADMAP.md` = ICE product future direction.
- `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md` = **canonical AI Weekend-07
  program record**.
- `docs/AI_W7_IMPLEMENTATION_SUMMARY.md` = plain-language AI learning summary.
- `docs/AI_W7_4_IMPLEMENTATION_REVIEW.md` = W7.4 checkpoint record.
- Milestone `*_IMPLEMENTATION_PLAN/REVIEW.md` = M-series scope/verification.
- Code and tests are the ground truth; any doc conflict resolves in their favor.