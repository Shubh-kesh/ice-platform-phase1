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

- **Branch:** `claude-development`; **HEAD:** `7795890` (M6 close-out test
  commit), **ahead of origin by 1** — the M6 close-out commit is not yet pushed.
- **Previous HEAD `3315957` (M13) is committed and pushed** to
  `origin/claude-development`.
- **Alembic revision (DB and repo in sync):** `j8e9f0a1b2c3` (M13
  `notifications`). Verified `alembic current` = `alembic heads` =
  `j8e9f0a1b2c3`; the local dev database was migrated in-place from
  `i7d8e9f0a1b2` to `j8e9f0a1b2c3` during reconciliation.
- **Backend tests:** **256 passing** (verified Aug 13, 2026 against real
  Postgres), including 12 M13 notification tests, 21 M12 scheduling tests,
  20 M11 Google tests, 17 M6 client-portal tests, and the Alembic
  upgrade/downgrade/replay chain through `j8e9f0a1b2c3`.
- **Frontend:** `npm run build` passes; `npm run lint` passes with 1
  pre-existing warning (`auth-context.tsx` Fast Refresh).
- **Quality gates:** ruff 2 / mypy 10 baselines met (delta gates PASS);
  `git diff --check` clean.
- **Working tree:** contains 7 untracked docs (see §3 §"Worktree
  classification"); no modified tracked files. Nothing else uncommitted.
- **Phase 4 production infrastructure (P4.2–P4.6):** intentionally **deferred**
  (owner decisions pending; see §4). P4.1 (CI/CD quality gates) is complete,
  committed, and CI-verified.

## 3. Completed Milestones

Chronological (all committed unless noted):

- **Phase 1** — foundation: auth, RBAC (4 roles), projects CRUD, Command
  Center, audit trail, seed data.
- **Phase 2** — tasks (Gantt), daily site logs, inventory ledger, finance
  schema scaffold.
- **M1** — inventory integrity: row-locked movements + ledger reconciliation.
- **M2** — project-assignment management (unique constraint, admin API/UI).
- **M4** — job costing with cost codes; `budget_spent` derived from ledger.
- **M10** — project lifecycle & admin: DRAFT→ACTIVE→COMPLETED→ARCHIVED,
  auto project codes, archive visibility/read-only, seed gating.
- **M3** — computed health (timeline/budget/safety) + audited admin overrides.
- **M5** — milestone invoicing (schedule-of-values → invoices; client
  restricted shape).
- **M6** — client view-only portal (server-enforced contract). **Close-out
  (17 tests) committed as `7795890`** — detail isolation, archived-404,
  task/site-log read shapes, invoice allow/deny lists, IDOR, mutation matrix,
  Google-authenticated-client parity, and a role regression.
- **M7** — task date-order + dependency/cycle validation.
- **M8** — idempotency keys (transactional claim ledger).
- **M9** — token security: opaque rotated refresh sessions, revocation,
  deactivated cutoff, auth-event audit.
- **M11** — Google Sign-In (Authorization Code + PKCE, server-side ID-token
  verification, admin onboarding; real smoke verified).
- **M12** — dynamic Gantt: push-only Finish-to-Start scheduling, automatic
  cascade, `task_schedule_shift` audit.
- **M13** — in-app notifications & alerts (schedule/invoice/low-stock/
  assignment events; user-scoped feed API; AppShell bell). Committed `3315957`
  and pushed.
- **P4.1** — CI/CD & quality gates (GitHub Actions; baseline-delta gates).

## 4. Deferred / Explicitly Out-of-Scope Work

- **Phase 4 production infrastructure (P4.2–P4.6):** IaC (Terraform/Cloud
  Run), managed Postgres/Redis, secrets management, observability,
  Redis-backed rate limiting, staging/GO-NO-GO gate — explicitly postponed.
  Decision report: `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md` (D1–D9 owner
  decisions unapproved); plan: `docs/PHASE4_IMPLEMENTATION_PLAN.md`.
  **Recommended stack (unapproved):** GCP Cloud Run + Cloud SQL + Memorystore
  + Secret Manager + Workload Identity.
- **Email/SMS/web-push notification delivery** — M13 is in-app only; external
  delivery needs a provider + secret management (deferred).
- **7-day low-stock demand forecast** — static reorder-threshold alerts only;
  forecast is Phase 5 (needs a worker).
- **Phase 5** (vendors/POs/QR-photo verification/3-location inventory),
  **Phase 6** (daily-log photos + voice-to-text, offline, quality hold-points,
  attendance), **Phase 7** (AI/ML), **Phase 8** (scale/SSO/compliance) —
  planned, not started.
- **httpOnly refresh-cookie transport** — M9-deferred; requires HTTPS env.
- **Frontend automated/E2E tests** — deferred (Playwright smoke is Phase 4).

## 5. Current Production/Demo Architecture

- **Development/demo:** Docker Compose (PostgreSQL 16, Redis 7, backend on
  `:8000` via gunicorn/uvicorn); frontend served by Vite dev server on
  `:5173`. Redis is provisioned but **unused by any code**.
- **Deployment target (documented, not built):** Render.com for feature/demo
  per the roadmap; Phase 4 production rails (IaC/secrets/observability) are
  deferred. GCP/Cloud Run is the recommended Phase 4 stack (unapproved).
- **Migrations** run at container startup (`alembic upgrade head`) in dev;
  `alembic/env.py` reads DB credentials from app settings (single source of
  truth).

## 6. Authoritative Documentation Hierarchy

| Purpose | Document |
|---|---|
| LLM bootstrap/navigation | `docs/AI_CONTEXT.md` (this file) |
| Current verified project state (facts, tests, limitations) | `docs/CURRENT_STATE.md` |
| System architecture and invariants | `docs/ARCHITECTURE.md` |
| Milestone direction and sequencing | `docs/ROADMAP.md` |
| Historical development/session record | `docs/SESSION_NOTES.md` |
| Approved milestone scope **before** implementation | `docs/M*_IMPLEMENTATION_PLAN.md` |
| Post-implementation verification (what was actually done) | `docs/M*_IMPLEMENTATION_REVIEW.md` |
| Current-session continuation state (temporary) | `docs/SESSION_HANDOFF.md` |
| Product vision | `docs/PRODUCT_REQUIREMENTS.md` (SRS-derived) |
| Prior comprehensive audit | `docs/TECHNICAL_AUDIT.md` |
| Phase 4 infrastructure decision pass | `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md` |

Order of trust: **code/tests > CURRENT_STATE.md > milestone reviews > plans >
ROADMAP.md > older docs**. `ARCHITECTURE.md` is older (Aug 9) and predates
M10–M13 endpoints; treat its structure as valid but verify current endpoint
surfaces in code.

## 7. RBAC / Security Invariants

- **Roles are ICE-owned.** Google authentication (M11) never grants or changes
  a role; Google identity is authoritative via `users.google_sub` (unique),
  and verified email is only a link path — never the identity key.
- **4 roles:** `admin`, `site_supervisor`, `procurement_manager`, `client`.
  Admin+procurement see all projects; supervisor/client only assigned ones
  (`project_access.assert_can_view_project`). ARCHIVED projects are 404 to
  non-admin/procurement (never leaked).
- **Client isolation is server-side (M6):** clients get only the
  `ProjectClientRead` / `InvoiceClientRead` shapes; money/health/inventory/
  finance/milestone surfaces are 403; clients can never mutate anything
  (mutation matrix pinned by 17 M6 tests).
- **M9 session architecture is authoritative:** opaque refresh tokens stored
  only as SHA-256 digests, row-locked rotation, family revocation on reuse,
  server-side logout, deactivated-user cutoff; access JWTs stay stateless.
  httpOnly-cookie transport deferred.
- **Lifecycle/archive (M10):** status moves only through audited admin
  transitions; no hard deletes (soft lifecycle only).
- **Transactions + locking:** mutations commit their data change + audit row
  atomically; project-scoped writes (tasks, inventory movements, job costs,
  lifecycle, invoicing, scheduling) serialize on a project row lock; a failed
  request never leaves a half-applied change. Inventory movements additionally
  lock the item row.
- **Audit:** `record_audit()` in the same transaction as the mutation; no
  second audit system. `audit_logs` and `daily_site_logs` are append-only
  (no update/delete endpoints).
- **Money** = `Numeric(14,2)`; quantities `Numeric(12,2)`; inventory ledger
  (`stock_movements`) is immutable and the source of truth.
- **Migration discipline:** additive Alembic revisions in one linear chain;
  upgrade/downgrade/replay is chain-tested; destructive downgrades guarded.

## 8. Database / Migration State

- **Repo Alembic head = applied DB revision = `j8e9f0a1b2c3`** (M13
  `notifications`), verified in sync after in-place dev-DB migration.
- **M13 migration** adds the `notifications` table (uuid PK, `user_id` FK
  users CASCADE, `project_id` FK projects CASCADE nullable, constrained
  `type` String — app-level enum, `title`/`body`/`link`, `read_at`,
  `created_at`), plus `ix_notifications_user_read` and
  `ix_notifications_user_created` indexes.
- Migration chain (11 revisions): `5d2e53a7df4e` (initial) →
  `8f3a1c2d9e01` (Phase 2) → `a4b6c8d9e2f3` (M1) → `b5c7d9e1f203` (M2) →
  `c6d8e0f2a415` (M4) → `d7e9f1a2b3c4` (M10) → `e8f2a3c5b7e4` (M3) →
  `f3a4b5c6d7e8` (M8) → `g5b6c7d8e9f0` (M5) → `h6c7d8e9f0a1` (M9) →
  `i7d8e9f0a1b2` (M11) → `j8e9f0a1b2c3` (M13). M6/M7/M12 had no migration.

## 9. Test / Quality Baseline

- **Backend:** `pytest` (async, real Postgres; disposable `ice_test_db`):
  **256 passing** (verified Aug 13, 2026). Includes the migration-chain test
  (`backend/tests/test_migrations.py`) through `j8e9f0a1b2c3`.
- **Frontend:** `npm run build` (tsc + vite) passes; `npm run lint` (oxlint)
  passes with 1 pre-existing `auth-context.tsx` Fast-Refresh warning.
- **Lint/type debt (gated, not fixed):** ruff 2 and mypy 10 pre-existing
  findings in `.ci/baseline_{ruff,mypy}.txt`, oxlint 1 in
  `.ci/baseline_oxlint.txt`. Enforced as a CI delta gate (P4.1) via
  `scripts/ci_quality.py` — **new findings fail the gate; baseline debt must
  not increase** and may only be reduced by deleting genuinely-fixed lines.
- **CI:** `.github/workflows/ci.yml` runs on PR/push: ruff, mypy, pytest
  (incl. migration chain), `git diff --check`, frontend build + oxlint.
- **Coverage:** ~75% overall; no frontend tests.
- **Commands:** backend `cd backend && pytest tests/ -v`; frontend
  `npm run build` / `npm run lint`. Note: `pytest` is **not** installed in the
  Docker runtime image — run tests from the host.

## 10. Current Known Technical Debt / Risks

- Pre-existing lint/type baseline: ruff 2, mypy 10, oxlint 1 (must not
  increase).
- Refresh token in `localStorage` (XSS surface; M9-deferred httpOnly cookie).
- Rate limiting is in-memory/per-process (Phase 4 item).
- Synchronous `httpx` in async Google callback handlers (M11 residual).
- Admin self/last-admin deactivation unguarded (M11 residual).
- No frontend automated tests; audit listing lacks an index; a few DB
  uniqueness stubs remain (`inventory_items(project_id,name)`,
  `daily_site_logs(project_id,log_date)`).
- Full list: `docs/CURRENT_STATE.md` §5–§8.

## 11. Remaining Feature Roadmap

From `docs/ROADMAP.md` (Phase 5 → Phase 8). Phase 4 production rails are
deferred pending owner decisions.

- **Phase 5 — Procurement & Multi-Location Inventory:** vendors, purchase
  orders + line ops + lifecycle, QR/photo delivery verification releasing
  stock, warehouse/transit/site location dimension, 7-day low-stock forecast.
- **Phase 6 — Field Experience:** photo upload + gallery per daily log, voice
  capture, offline-first PWA with sync/conflict resolution, quality
  hold-points/phase gates, attendance + toolbox talks, mobile-first UI.
- **Phase 7 — AI/ML:** data pipeline, predictive delay-risk with confidence +
  human-review trail, CV QC anomaly detection, drawing→BOQ suggestions.
- **Phase 8 — Scale & Maturity:** regional compliance reporting, portfolio
  forecasting, SSO/OIDC beyond Google, multi-tenant.

Sequencing guardrail: no phase ships to production without Phase 4 rails; if a
cut is forced, preserve Phase 3 → Phase 4 → Phase 6 → Phase 7 (procurement is
the most safe to trim/reorder).

## 12. How a Fresh OpenCode Session Must Reconstruct Context

1. Read `docs/AI_CONTEXT.md` (this file).
2. Read `docs/CURRENT_STATE.md` and `docs/ROADMAP.md`.
3. Read `docs/SESSION_HANDOFF.md` (if present) for the latest continuation
   state — it is a snapshot, not authority over code/tests.
4. Read the relevant milestone implementation plan (before) / review (after)
   for the active milestone.
5. Inspect `git status`, `git log --oneline -5`, and branch tracking.
6. Verify `alembic current` matches the repo head before relying on any DB
   feature; reconcile the dev DB if it lags.
7. Confirm test/quality baselines (pytest count, frontend build/lint, CI
   gates) match the documented numbers before declaring work complete.
8. Do not implement anything until the current milestone and its approved plan
   are understood; never silently expand milestone scope.
9. Do not modify an approved implementation plan after implementation begins.
10. Do not commit or push unless explicitly instructed.

## 13. Context Compaction / Handoff Protocol

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
