# ICE Platform — AI Context

Primary bootstrap document for OpenCode/LLM sessions. Short, stable,
navigational. It does **not** replace the authoritative docs it points to.
Read the cited documents for detail; verify anything that matters against
code/tests (source code is the ground truth).

## 1. Project Purpose

**ICE (Intelligent Construction Engine)** is a multi-site residential
construction ERP managing ~10–15 projects at once: scheduling/Gantt, daily
site logs, inventory, job costing, milestone invoicing, computed project
health, and in-app notifications in one dashboard. Stack: React 19 + Vite SPA
(TanStack Query, axios) · FastAPI (async SQLAlchemy, asyncpg) · PostgreSQL 16
· Alembic · Docker Compose (dev). Single-service monolith; Redis is
provisioned but unused. Source of product vision:
`docs/PRODUCT_REQUIREMENTS.md`.

## 2. Current Repository State

- **Branch:** `claude-development`; **HEAD:** `ce88b1f` (new developer
  directory code push); **in sync with `origin/claude-development`**; working
  tree clean.
- **AI learning workstream (Weekend 01–07): COMPLETE and committed.** W7.1
  memory/context, W7.2 web/retry, W7.3 middleware/resilience, and W7.4
  HITL/actions are all implemented and committed at `ce88b1f`. Canonical
  records: `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md` (final program review),
  `docs/AI_W7_4_IMPLEMENTATION_REVIEW.md` (W7.4 checkpoint),
  `docs/AI_W7_IMPLEMENTATION_SUMMARY.md` (plain-language).
- **No AI milestone is currently in flight.** Weekend 08+ course material does
  not exist yet in `mayank953/Live-Class-2026` (course ends at Weekend 07 /
  Class 12). Next AI work waits for user/course Weekend 08+ — do not invent a
  new AI milestone.
- **Alembic repository head:** `l5d6e7f8a9b0` (M15 `receiving/deliveries`).
  The migration chain (upgrade → downgrade → replay) is chain-tested through
  this revision in `backend/tests/test_migrations.py`.
- **Backend tests:** **462 passing** (verified Aug 18, 2026 against real
  Postgres), including **128 AI tests** (tools/RBAC, agent loop, SSE API,
  provider factory, memory, web search, middleware, HITL lifecycle incl.
  double-resume replay, mutating-tool RBAC, W7.4 concepts) plus the full
  M1–M15 suite and the Alembic upgrade/downgrade/replay chain.
- **Frontend:** `npm run build` passes; oxlint delta gate PASS (1 pre-existing
  `auth-context.tsx` Fast-Refresh warning).
- **Quality gates:** ruff current=2 vs baseline=2 PASS, mypy current=10 vs
  baseline=10 PASS (no new findings; 2 of the baseline entries are jose/passlib
  stub warnings that resolve if `types-python-jose`/`types-passlib` are
  installed — CI does not install them), oxlint current=1 vs baseline=1;
  `git diff --check` clean; secret scan clean.
- **Environment note:** the host conda base env is drifted (fastapi 0.116 /
  starlette 1.6 break imports). Run tests in the pinned
  `requirements-dev.txt` venv or the Docker image (fastapi 0.115.0, starlette
  0.38.6), NOT the host conda env.
- **Phase 4 production infrastructure (P4.2–P4.6):** intentionally **deferred**
  (owner decisions pending; see §4). P4.1 (CI/CD quality gates) is complete.

## 3. Completed Milestones

Chronological (all committed):

- **Phase 1** — foundation: auth, RBAC (4 roles), projects CRUD, Command
  Center, audit trail, seed data.
- **Phase 2** — tasks (Gantt), daily site logs, inventory ledger, finance
  schema scaffold.
- **M1–M15** — inventory integrity, assignments, job costing, computed health,
  invoicing, client portal, task validation, idempotency, token security,
  lifecycle, Google Sign-In, dynamic Gantt, notifications, vendors/POs, PO
  receiving. (See `docs/CURRENT_STATE.md` §2–§4 for details.)
- **P4.1** — CI/CD & quality gates (GitHub Actions; baseline-delta gates).
- **AI-1 — ICE Copilot** (commit `f7da04d`): read-only Copilot foundation.
- **Weekend 01–07 (W7.1–W7.4, commit `ce88b1f`):** the AI learning workstream
  through the whole taught course — see §3b.

## 3b. AI Learning Workstream — Weekend 01–07 (COMPLETE)

A separate, concurrently-running AI-learning workstream (M-series development
paused). Highlights:

- **W7.1 memory/context:** user-namespaced thread memory (`{user_id}::{thread_id}`)
  on the process-local InMemorySaver; summarization + context-editing
  middleware; thread listing. Cross-user thread access is structurally
  impossible and tested.
- **W7.2 web/retry:** Tavily-compatible `web_search` via a direct async httpx
  wrapper (no SDK); `ToolRetryMiddleware` scoped to transient external
  failures only (deterministic DB/domain errors never retried — test-pinned).
- **W7.3 middleware/resilience:** explicit `build_middleware` order — PII
  (input) → memory → ModelCallLimit → ModelRetry → ModelFallback →
  ToolSelector → ToolCallLimit (global + web) → ToolRetry (web). Catalog
  expanded to 15 read-only tools with per-tool RBAC.
- **W7.4 HITL/actions:** HumanInTheLoopMiddleware interrupts only the two
  low-risk mutating tools (`create_task`, `create_daily_site_log`); decisions
  approve/edit/reject/respond via `POST /assistant/resume` →
  `Command(resume=...)` on the same user-owned thread. Double-resume (replaying
  the same approval) is a safe `no_pending_approval` no-op — pinned by a
  regression test. Mutations default OFF (`ICE_AI_MUTATIONS_ENABLED=false`).
- **Final tool catalog (17):** 15 read-only + `web_search` + 2 mutating
  (HITL-guarded, default OFF). Every tool self-authorizes from
  `ToolRuntime.context`.
- **Backend:** `app/ai/` (context, security, prompts, agent, logging, memory,
  middleware, pii, models, web_search, tools incl. mutating),
  `api/v1/assistant.py` (chat SSE + capabilities + resume).
- **Frontend:** React `/assistant` page with memory + thread list, web-search
  flag, and an approval card (Approve/Edit/Reject with editable fields).
- **Pinned AI deps:** langchain 1.3.15 · core 1.5.5 · openai-int 1.5.1 ·
  anthropic-int 1.5.6 · groq-int 1.1.3 · langgraph 1.2.11 family (pinned) ·
  openai 2.54.0 · fastapi 0.115.0 · starlette 0.38.6.
- **Verified:** backend 462 (128 AI), frontend build + oxlint, ruff/mypy/oxlint
  deltas PASS, all 20 `ai_labs/` demos run clean, secret scan clean.
- **Learning labs:** 20 self-contained `backend/ai_labs/` demos (never imported
  by `app/`, each with a README).
- **Weekend 08+ deferred (course material not yet released):** RAG/embeddings,
  MCP, multi-agent/sub-agents, autonomous agents, advanced semantic long-term
  memory, durable threads/approvals.

## 4. Deferred / Explicitly Out-of-Scope Work

- **Phase 4 production infrastructure (P4.2–P4.6):** IaC (Terraform/Cloud
  Run), managed Postgres/Redis, secrets management, observability,
  Redis-backed rate limiting, staging/GO-NO-GO gate — explicitly postponed.
  Decision report: `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md` (D1–D9 owner
  decisions unapproved); plan: `docs/PHASE4_IMPLEMENTATION_PLAN.md`.
- **Phase 5 remainder** (locations/forecast M16), **Phase 6** (daily-log photos
  + voice-to-text, offline, quality hold-points, attendance), **Phase 7** (the
  product's own AI/ML: predictive delay / CV-QC / BOQ), **Phase 8**
  (scale/SSO/compliance) — planned.
- **Weekend 08+ AI concepts** (RAG, MCP, multi-agent, autonomous agents,
  durable threads/approvals) — **wait for the course material**, do not invent.
- **Email/SMS/web-push notification delivery** — M13 is in-app only.
- **httpOnly refresh-cookie transport** — M9-deferred; requires HTTPS env.
- **Frontend automated/E2E tests** — deferred.

## 5. Current Production/Demo Architecture

- **Development/demo:** Docker Compose (PostgreSQL 16, Redis 7, backend on
  `:8000` via gunicorn/uvicorn); frontend served by Vite dev server on
  `:5173`. Redis is provisioned but **unused by any code**. Start
  `docker compose up -d postgres` before relying on the live DB.
- **Deployment target (documented, not built):** Render.com for feature/demo
  per the roadmap; Phase 4 production rails (IaC/secrets/observability) are
  deferred.
- **Migrations** run at container startup (`alembic upgrade head`) in dev;
  `alembic/env.py` reads DB credentials from app settings.
- **Dev-workflow gotcha:** compose bind-mounts only `backend/app`; `alembic/
  versions` is baked into the image — **rebuild the backend image after every
  migration change** (`docker compose build backend && docker compose up -d
  backend`).

## 6. Authoritative Documentation Hierarchy

| Purpose | Document |
|---|---|
| LLM bootstrap/navigation | `docs/AI_CONTEXT.md` (this file) |
| Current verified project state (facts, tests, limitations) | `docs/CURRENT_STATE.md` |
| System architecture and invariants | `docs/ARCHITECTURE.md` |
| Milestone direction and sequencing | `docs/ROADMAP.md` |
| Approved milestone scope **before** implementation | `docs/M*_IMPLEMENTATION_PLAN.md` |
| Post-implementation verification (what was actually done) | `docs/M*_IMPLEMENTATION_REVIEW.md` |
| Current-session continuation state (temporary) | `docs/SESSION_HANDOFF.md` |
| Product vision | `docs/PRODUCT_REQUIREMENTS.md` (SRS-derived) |
| AI workstream: final Weekend-07 program review | `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md` |
| AI workstream: W7.4 checkpoint review | `docs/AI_W7_4_IMPLEMENTATION_REVIEW.md` |
| AI workstream: plain-language learning summary | `docs/AI_W7_IMPLEMENTATION_SUMMARY.md` |
| AI workstream: historical AI-1 records | `docs/AI1_IMPLEMENTATION_REVIEW.md` / `AI1_IMPLEMENTATION_SUMMARY.md` |

Order of trust: **code/tests > CURRENT_STATE.md > milestone reviews > plans >
ROADMAP.md > older docs**. `ARCHITECTURE.md` is older (Aug 9) and predates
M10–M15 + AI surfaces; treat its structure as valid but verify current
endpoint surfaces in code.

## 7. RBAC / Security Invariants

- **Roles are ICE-owned.** Google authentication (M11) never grants or changes
  a role; Google identity is authoritative via `users.google_sub` (unique).
- **4 roles:** `admin`, `site_supervisor`, `procurement_manager`, `client`.
  Admin+procurement see all projects; supervisor/client only assigned ones
  (`project_access.assert_can_view_project`). ARCHIVED projects are 404 to
  non-admin/procurement (never leaked).
- **Client isolation is server-side (M6):** clients get only the
  `ProjectClientRead` / `InvoiceClientRead` shapes; money/health/inventory/
  finance/milestone surfaces are 403; clients can never mutate anything.
- **M9 session architecture is authoritative:** opaque refresh tokens stored
  only as SHA-256 digests, row-locked rotation, family revocation on reuse,
  server-side logout, deactivated-user cutoff.
- **Lifecycle/archive (M10):** status moves only through audited admin
  transitions; no hard deletes.
- **Transactions + locking:** mutations commit their data change + audit row
  atomically; project-scoped writes serialize on a project row lock.
- **Audit:** `record_audit()` in the same transaction as the mutation;
  `audit_logs` and `daily_site_logs` are append-only.
- **Money** = `Numeric(14,2)`; quantities `Numeric(12,2)`; inventory ledger
  (`stock_movements`) is immutable and the source of truth.
- **Migration discipline:** additive Alembic revisions in one linear chain;
  upgrade/downgrade/replay chain-tested.
- **AI Copilot invariants (authoritative, all test-pinned):** identity is
  injected via `ToolRuntime.context` (`context_schema=ActorContext`) — never a
  model argument; every AI tool independently enforces the same REST-equivalent
  RBAC; the role-filtered tool catalog is defense-in-depth only; client AI
  tools == the M6 client portal set; no `execute_sql`/generic DB tool;
  provider/model/base_url/API keys are server-controlled; thread ownership is
  user-namespaced (cross-user resume impossible); HITL approval never bypasses
  RBAC (client approve → still denied); HITL approvals are **single-use**
  (double-resume returns `no_pending_approval`, no duplicate mutation/audit —
  regression-pinned); execution logging is sanitized (no secrets, identity
  args, raw results, chain-of-thought).

## 8. Database / Migration State

- **Repo Alembic head = `l5d6e7f8a9b0`** (M15 `deliveries`/`delivery_lines` +
  `po_status` extension). Live dev DB verified at the same revision. AI work
  added **no migrations** (W7.1–W7.4 are schema-free).
- Migration chain (14 revisions) through `l5d6e7f8a9b0` — see
  `docs/CURRENT_STATE.md` §8 for the full chain.

## 9. Test / Quality Baseline

- **Backend:** `pytest` (async, real Postgres; disposable `ice_test_db`):
  **462 passing** (verified Aug 18, 2026) — full M1–M15 suite **plus 128 AI
  tests**. Includes the migration-chain test through `l5d6e7f8a9b0` (M15).
- **Frontend:** `npm run build` (tsc + vite) passes; `npm run lint` (oxlint)
  passes with 1 pre-existing `auth-context.tsx` Fast-Refresh warning.
- **Lint/type debt (gated, not fixed):** ruff 2 and mypy 10 pre-existing
  findings in `.ci/baseline_{ruff,mypy}.txt`, oxlint 1 in
  `.ci/baseline_oxlint.txt`. Enforced as a CI delta gate (P4.1) via
  `scripts/ci_quality.py`. The mypy baseline includes 2 jose/passlib stub
  warnings that resolve if the stub packages are installed (not in CI); the
  gate stays PASS either way.
- **CI:** `.github/workflows/ci.yml` runs on PR/push: ruff, mypy, pytest
  (incl. migration chain), `git diff --check`, frontend build + oxlint.
- **Commands:** backend `cd backend && pytest tests/ -v` (requires Postgres +
  the pinned `requirements-dev.txt` venv — the host conda env is drifted);
  frontend `npm run build` / `npm run lint`.

## 10. Current Known Technical Debt / Risks

- Pre-existing lint/type baseline: ruff 2, mypy 10 (now 8 current), oxlint 1.
- Refresh token in `localStorage` (XSS surface; M9-deferred httpOnly cookie).
- Rate limiting is in-memory/per-process (Phase 4 item).
- AI thread memory + pending approvals are process-local (InMemorySaver) — a
  restart loses memory and pending HITL approvals (documented W7.1/W7.4
  limitation; durable threads are a Weekend-08+ item).
- No frontend automated tests; a few DB uniqueness stubs remain.
- Full list: `docs/CURRENT_STATE.md` §5–§8.

## 11. Remaining Feature Roadmap

From `docs/ROADMAP.md` (Phase 5 → Phase 8). Phase 4 production rails are
deferred pending owner decisions. The AI learning workstream is complete
through Weekend 07 and **waits for Weekend 08+ course material** — the ICE
feature development (Phase 5+) can resume independently when requested.

## 12. Current Milestones

**M15 — PO Delivery Verification / Receiving — DONE** (committed).

**AI learning workstream — Weekend 01–07 COMPLETE** (committed at `ce88b1f`).
**No AI milestone in flight.** Next step: wait for the user/course to provide
Weekend 08+ material; do not invent new AI milestones. M-series development
remains paused separately (next product milestone after M15 would be M16).

## 13. How a Fresh OpenCode Session Must Reconstruct Context

1. Read `docs/AI_CONTEXT.md` (this file).
2. Read `docs/CURRENT_STATE.md` and `docs/ROADMAP.md`.
3. Read `docs/SESSION_HANDOFF.md` (if present) — a snapshot, not authority
   over code/tests.
4. For the AI workstream, read `docs/AI_WEEKEND7_IMPLEMENTATION_REVIEW.md`
   (final program record) and `docs/AI_W7_IMPLEMENTATION_SUMMARY.md`
   (plain-language).
5. Inspect `git status`, `git log --oneline -5`, and branch tracking.
6. Verify `alembic current` matches the repo head **after starting Docker**
   (Postgres required for tests).
7. Confirm test/quality baselines (pytest count, frontend build/lint, CI
   gates) match the documented numbers before declaring work complete.
8. Do not implement anything until the current milestone and its approved plan
   are understood; never silently expand milestone scope.
9. Do not commit or push unless explicitly instructed.

## 14. Context Compaction / Handoff Protocol

```
NORMAL SESSION
  → read AI_CONTEXT
  → inspect relevant docs/code
  → work on current task

AT ~70–80% CONTEXT
  → stop major implementation
  → create/update docs/SESSION_HANDOFF.md
  → record exact current state and next action
  → start fresh session

NEW SESSION
  → read AI_CONTEXT
  → read CURRENT_STATE
  → read SESSION_HANDOFF (if present)
  → read the relevant milestone plan/review
  → inspect git status
  → continue only after reconstructing state
```

Update `docs/SESSION_HANDOFF.md` as a **fresh, current-only** document at every
handoff — never carry stale HEAD hashes or test counts forward.