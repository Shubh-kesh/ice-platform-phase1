# Current State of the Software

**Document:** Actual implementation state of the ICE platform today
**Date:** August 10, 2026
**Basis:** Source-code inspection + verified runs (54 backend tests pass, live DB inspected)
**Warning:** This document describes what EXISTS today, not the product vision. The roadmap is in `docs/PRODUCT_REQUIREMENTS.md`; the current reality is here.

---

## 1. Current architecture

A single-service monolith.

```
React 19 SPA (Vite, no SSR)
   │  axios -> /api/v1  (Bearer JWT access token in memory; refresh token in localStorage)
   v
FastAPI app (backend/app/main.py)
   |- CORS (fixed origin list) -- slowapi rate limiter (in-memory, per-process)
   |- v1 routers: auth, users, projects, audit, tasks, site_logs, inventory
   |     |- RBAC via deps.require_role / project_access.assert_can_view_project
   |     `- Business logic INLINE in route handlers (no services/repositories layer)
   v
SQLAlchemy 2.0 async (asyncpg) --> PostgreSQL 16
   `- record_audit() writes AuditLog inside the same transaction as the mutation
```

- **Frontend:** React 19 + Vite + TanStack Query + react-router-dom + axios + Tailwind. 3 routes: `/login`, `/` (Command Center), `/projects/:projectId`.
- **Backend:** FastAPI, async SQLAlchemy ORM, Alembic migrations, bcrypt + JWT, slowapi rate limiting. All business logic lives inside `api/v1/*` route files.
- **Database:** PostgreSQL 16, 11 tables, 2 applied migrations.
- **Deployment:** Docker + docker-compose (local dev). Multi-stage non-root Dockerfile, 4 gunicorn workers, healthcheck, migrations run on container start.
- **Redis:** provisioned in compose, configured in settings, **never used by any code**.
- **Not present:** separate services layer, repositories, queues/workers, caching, file storage, notifications, external integrations, monitoring, CI/CD, IaC.

## 2. Implemented modules

| Module | Backend | Frontend | Notes |
|---|---|---|---|
| Authentication | `api/v1/auth.py`, `core/security.py`, `core/rate_limit.py` | `lib/auth-context.tsx`, `lib/api.ts`, `pages/Login.tsx` | JWT access (30m) + refresh (7d); bcrypt; login rate-limited 5/min |
| Users (admin CRUD) | `api/v1/users.py` | — | Admin-only; password policy 8 chars + 1 uppercase + 1 digit |
| Projects + health | `api/v1/projects.py`, `models/project.py` | `CommandCenter.tsx`, `ProjectCard.tsx`, `KpiStrip.tsx`, `HealthDot.tsx`, `ProjectDetail.tsx`, `ProjectAssignments.tsx` | 3 color-coded health fields, manual; admin-assignable team panel (Phase 3 M2) |
| Audit trail | `models/audit.py`, `middleware/audit.py`, `api/v1/audit.py` | — | Admin read endpoint only |
| Tasks / Gantt bars | `models/task.py`, `api/v1/tasks.py` | `ProjectTimeline.tsx` | Flat task list per project |
| Daily site logs | `models/site_log.py`, `api/v1/site_logs.py` | `DailySiteLogs.tsx` | Append-only create/read |
| Inventory ledger | `models/inventory.py`, `api/v1/inventory.py`, `services/inventory.py` | `InventoryPanel.tsx` | Items + row-locked signed stock-movement ledger; reconciliation report (`GET /projects/{id}/inventory/reconciliation`) |
| Finance (job costing) | `models/finance.py`, `api/v1/finance.py`, `services/finance.py`, `schemas/finance.py` | `JobCostsPanel.tsx` | `cost_code` enum; job-cost CRUD; `budget_spent` derived from `SUM(job_costs)`; budget roll-up report (Phase 3 M4) |
| Finance (invoices) | `models/finance.py` | — | Tables only, **no endpoints** (M5) |
| Seed/demo data | `seed.py` | — | 4 role users + 15 projects |

## 3. Phase 1 completed functionality

- Email/password login, token refresh, `/auth/me`.
- JWT access + refresh tokens; bcrypt password hashing.
- Rate limiting on login (5/min) and refresh (10/min) per process.
- Password policy enforced at user creation (min 8 chars, 1 uppercase, 1 digit).
- Four roles: admin, site_supervisor, procurement_manager, client.
- RBAC: admin-only for user/project mutations; supervisors/clients scoped to assigned projects via `project_assignments`.
- Project-assignment management API (Phase 3 M2): admin assigns/unassigns supervisors/clients via `GET/POST/DELETE /projects/{id}/assignments`, audited, unique-constrained, take effect within one request.
- Projects CRUD with status + timeline/budget/safety health enums + budgets + dates.
- Command Center UI: project cards, KPI strip, per-project health dots, drill-down detail page.
- Audit logging on user and project create/update; admin read endpoint `GET /api/v1/audit/logs`.
- Seed script: 1 user per role and 15 residential demo projects with assignments.
- Backend test framework and initial auth/users/RBAC tests.

## 4. Phase 2 completed functionality

- **Tasks:** CRUD per project (`GET/POST /projects/{id}/tasks`, `PATCH/DELETE .../{task_id}`), status + percent-complete, optional `depends_on_id`, `sort_order`. Timeline UI with proportional bars, status dropdown, progress slider, delete.
- **Daily site logs:** append-only `GET/POST /projects/{id}/site-logs` with date, work summary, issues, workers present, weather, `photo_urls` (always empty). Feed + create form UI.
- **Inventory:** items per project (`GET/POST /projects/{id}/inventory`), `PATCH .../{item_id}`, stock movements (`GET/POST /projects/{id}/inventory/{item_id}/movements`). Immutable signed ledger; negative-balance guard rejects with 400; `quantity_on_hand` denormalized running total. UI with low-stock flag, add-item form, movement form.
- **RBAC for Phase 2:** admin/supervisor write tasks and logs (supervisor only on assigned projects); admin/procurement write inventory; read follows project access for all.
- **Audit wiring:** every Phase 2 mutation records an audit row in the same transaction.
- **Finance schema:** `job_costs`, `invoices` tables migrated (no API/frontend).
- **Shared helpers:** `project_access.py` extracted and used by all project-scoped routes.
- **Tests:** task, site-log, and inventory suites (33 total backend tests, all pass against real Postgres).

## 4b. Phase 3 completed functionality

- **Finance (P3 M4):** Job-costing landed — `cost_code` enum (`foundation`…`other`), `GET/POST /projects/{id}/job-costs` + `PATCH/DELETE .../{cost_id}` (admin/procurement read **and** write — cost line items are budget data and are 403 for clients/supervisors), and `GET /projects/{id}/budget` (admin/proc roll-up: total / spent / remaining / by-cost-code). `Project.budget_spent` is now **derived** from `SUM(job_costs.amount)` in the same transaction as every mutation (denormalized running total, like `quantity_on_hand`), and job-cost mutations lock the project row (`SELECT ... FOR UPDATE`, the M1 inventory pattern) so concurrent writes can't drift the total from the ledger — the acceptance invariant `budget_spent == SUM(job_costs)` holds. Finance service follows the Phase 3 thin-services pattern (`app/services/finance.py`, pure domain math). Invoices remain schema-only (M5).
- **Testing (P3 M4):** `tests/test_finance.py` — 12 tests covering create/update/delete budget recompute, roll-up split, supervisor write-403, client+supervisor read-403, client budget-403, amount validation, 404s, and a concurrent-WRITE row-lock regression test (no lost budget update).

## 5. Partially implemented functionality

- **Dynamic Gantt:** tasks and dependency column exist, but changing a task date does **not** shift downstream tasks, and there are **no vendor notifications**. The frontend never sends `depends_on_id`.
- **Health indicators:** fields exist and render on the dashboard, but are **manual/typed** by admin/supervisor — nothing computes them from schedule or cost data.
- **Low-stock alerts:** UI flags `quantity_on_hand <= reorder_threshold` only; there is no 7-day scheduled-demand calculation and no alerting mechanism.
- **Daily site logs:** text fields fully work; the mandatory "5 photos + voice-to-text" capture does not — `photo_urls` is always an empty list.
- **Audit trail:** covers CRUD on users/projects/tasks/logs/inventory but not login/refresh events; `ip_address` is never populated.
- **Client experience:** the Client role can log in and view assigned projects/tasks/logs, but sees full budget figures — this is not the PRD's view-only photo/invoice portal.
- **Finance:** job-costing endpoints exist (P3 M4); invoice CRUD + milestone-based invoicing still not implemented (see Known limitations).

## 6. Known bugs

- **Concurrent stock movements can lose updates — RESOLVED (Phase 3, M1):** `record_movement` now locks the item row (`SELECT ... FOR UPDATE`) so simultaneous movements serialize instead of both deciding against the same starting balance. A concurrency test fires two parallel consumptions (both persist, on-hand = 40 after 2×30 from 100) and `GET /projects/{id}/inventory/reconciliation` recomputes each item's balance from the ledger to surface any legacy drift. (`api/v1/inventory.py`, `services/inventory.py`)
- **Task `PATCH` skips date-order validation:** create validates `end_date >= start_date`; update does not — a malformed task (end before start) can be saved via `PATCH`. (`schemas/task.py`)
- **Task dependency cycles allowed:** `depends_on_id` can be set to form a self-reference or cycle; not checked on create or update.
- **Duplicate-ish data allowed — partially RESOLVED:** duplicate `project_assignments` rows are now impossible (unique constraint + API returns 409, Phase 3 M2); duplicate inventory item names per project, and multiple daily site logs per day, still have no uniqueness constraints.
- **`uuid.UUID(user_id)` can raise `ValueError` -> 500** in `deps.py:45` and `auth.py:55` when a token carries a non-UUID subject (low exploitability, tokens are signed).
- **Backend lint/type failures:** `ruff check app` reports 5 unused-import (F401) errors; `mypy app` reports 10 errors (broken `Mapped["Project"]` forward references in 4 model files, config args).
- **`ip_address` on audit entries is always NULL** — the parameter exists but is never passed.

## 7. Technical debt

- **No services/repositories layer:** route handlers mix dependency injection, authorization, validation, business logic, DB access, and audit in single functions.
- **Duplicated audit-pattern code:** the "build changes dict from `model_dump(exclude_unset=True)`" pattern is copy-pasted in `users.py:79`, `projects.py:91`, `tasks.py:100`, `inventory.py:111`.
- **Dead code / unused dependencies:** `redis` and `tenacity` in requirements (never used); `GCP_PROJECT_ID` / `GCS_BUCKET_NAME` config stubs; `Invoice` model + finance enum imports used only partially; project idle health code is manual.
- **Dangling abstraction:** `invoices` models exist with no endpoints consuming them (M5).
- **Inconsistent patterns:** `_get_item_or_404` vs `get_project_or_404`; per-module `write_roles`; inconsistent route shapes (`/audit/logs` vs flat collections).
- **Lint/type debt is un-gated** (no CI).
- **Stale root documentation:** `QUICK_START.md`, `PHASE2_READY.md`, `IMPLEMENTATION_SUMMARY.txt`, `CRITICAL_FIXES_IMPLEMENTED.md` contradict the code (e.g., claim SQLite in-memory tests; code uses real Postgres; "15+ tests" vs 33) and overstate readiness.
- **Unused `ip_address` parameter** in `record_audit` is a misleading API.

## 8. Security concerns

1. **Refresh token stored in `localStorage`** (`frontend/src/lib/api.ts`) — any XSS payload can exfiltrate the long-lived token. The access token is correctly kept in memory.
2. **Refresh tokens are un-rotated and have no server-side revocation:** `/auth/refresh` issues a fresh pair indefinitely; logout is purely client-side; deactivated users are only cut off on the next token validation.
3. **Rate limiting is in-memory and per-process:** with 4 gunicorn workers the effective login limit is ~4x; and `get_remote_address` uses `request.client.host`, so behind a reverse proxy every user shares one IP value, letting a global limit be exhausted or bypassed.
4. **Client role can read project budgets** via the standard project response when assigned.
5. **No audit** of login/refresh events remains; project assignments are now audited (`assign`/`unassign`, Phase 3 M2).
6. **Audit immutability by convention only:** nothing at the DB level prevents UPDATE/DELETE of `audit_logs` rows.
7. **Password policy is minimal:** 8 chars + 1 uppercase + 1 digit; no maximum length (bcrypt truncates at 72 bytes).
8. **Compose/demo config:** `docker-compose.yml` hardcodes `SECRET_KEY: local-dev-secret-change-in-production`; `seed.py` ships known demo credentials. `.env` files are correctly gitignored.
9. **File upload surface does not exist** — must be designed safely (type/size validation, signed GCS URLs) before photo upload is added.
10. **Positive:** no SQL injection found (all parameterized ORM queries); no CSRF surface (Bearer-header auth + strict CORS allowlist); React auto-escaping throughout (no `dangerouslySetInnerHTML`).

## 9. Performance concerns

- **Inventory lost-update race** under concurrent writes (correctness > throughput; see Known bugs).
- **Audit listing** uses `ORDER BY created_at DESC` + `OFFSET/LIMIT` on an unindexed column; degrades as the log grows.
- **No server-side caching:** every dashboard/render re-hits Postgres; TanStack Query (client cache, 30s staleTime) is the only mitigation.
- **ProjectDetail fan-out:** 4 sequential API calls (project, tasks, site logs, inventory) per page open; no `Promise.all` / aggregate endpoint.
- **Full-object lists** (users, projects) with no projection or pagination — fine at 15 records, wrong at scale.
- **No N+1 patterns found** in the route layer (lists return scalars, no nested loads). Async/asyncpg throughout, no blocking calls in hot paths.
- **Redis provisioned but unused** — available headroom for rate-limiter persistence, caches, and queues.

## 10. Testing status

- **Backend tests: 54, all passing** against real Postgres (verified on Aug 10, 2026). Files: test_auth (9), test_users (8), test_tasks (7), test_site_logs (4), test_inventory (9 — incl. row-lock concurrency, ledger-reconciliation match/mismatch, reconciliation RBAC), test_projects (8 — assignment API admin/RBAC/duplicate/isolation), test_finance (9 — job-cost CRUD, budget recompute, roll-up split, RBAC, validation; Phase 3 M4).
- **Coverage: ~73%** overall (pytest-cov). Lowest areas: inventory `api/v1/inventory.py` 39%, `projects.py` 42%, `tasks.py` 42%.
- **Frontend tests: none** (no vitest/RTL config or tests).
- **Missing critical tests:** `test_projects.py` handles the assignment API but project CRUD, PATCH RBAC, health updates, and budget validation remain untested; audit endpoint (`/audit/logs`) untested; client read-isolation untested (row-lock concurrency and ledger-reconciliation now covered in Phase 3 M1); no migration-drift test; invoice (M5) and health (M3) not yet written.
- **Tooling:** pytest + pytest-asyncio + httpx; tests use a disposable `ice_test_db` Postgres database created/dropped per test. Ruff and mypy available in dev deps but **not CI-gated**.

## 11. Production readiness

**Not ready for production.**
- **Good:** multi-stage non-root Dockerfile with healthcheck; compose runs migrations on start; env-driven config; uniform 500 -> JSON error shape; request-latency logging.
- **Missing:** CI/CD (`.github/workflows/` empty); IaC (`infra/terraform/` empty); secrets management; structured logging/request IDs; metrics, tracing, alerting; backups/DR (single compose volume); multi-worker-safe rate limiting; automated migration application in prod; performance load-test at 15-project scale.

## 12. AI/ML readiness

**Not AI/ML-ready.** The intended CV-QC, predictive-delay, and drawing-to-BOQ features have no supporting infrastructure.
- **Usable today:** `tasks` schedule data (weak delay signal) and `stock_movements` (materials demand) are the only data usable as ML inputs.
- **Missing:** photo/image storage and serving pipeline (GCS is only a config stub); structured weather/vendor/delay feature data; any async worker/queue for inference; model-result + confidence + human-review audit storage; a replayable feature pipeline.
- **Sequencing implication:** predictive-delay is the most reachable first AI feature; CV-QC is the farthest away.

## 13. Known limitations

- **No project-assignment management API — RESOLVED (Phase 3 M2):** admins now assign/unassign supervisors and clients per project via `GET/POST/DELETE /projects/{id}/assignments` (admin-only, audited, unique-constrained). Users can be onboarded to sites through the system, making per-project RBAC operational rather than demo-only.
- **Finance**: job-costing is implemented (P3 M4, see §4b); **invoice CRUD, milestone-based invoicing, and accounting sync** are not (blocked on a provider/OAuth decision, per repo notes). Invoices remain schema-only.
- **No file uploads or voice capture** in daily site logs.
- **No offline-first / mobile-first experience:** it is a desktop web SPA; sidebar does not collapse; no PWA/service worker.
- **No notifications** (vendor, low-stock, milestone) — nothing emails/SMS/pushes.
- **No background jobs / schedulers** (health computation, demand forecasts).
- **No cross-project roll-up views** (inventory "Inventory"/"Finance"/"Quality & Safety" sidebar items are disabled Phase-2 stubs).
- **No pagination** on most list endpoints; no search/filtering.
- **No password change/reset flows** and no email infrastructure.
- **Tasks have no cascade re-scheduling** and dependency is effectively decorative.
- **Client portal** exposes budget figures rather than the intended photo/payment view.

## 14. Important architectural decisions

- **Monolith, not microservices:** one FastAPI service + one Postgres DB; a deliberate fit for 10-15 projects and a single owner-operator organisation.
- **Async SQLAlchemy + asyncpg end-to-end**, async FastAPI handlers, no blocking calls in hot paths.
- **Money as `Numeric(14,2)`**; dates as `Date`/`DateTime(timezone=True)`; Postgres-native types (UUID, JSONB, ENUM) throughout.
- **Ledger-over-denormalized-count for inventory:** `quantity_on_hand` is a denormalized running total, with `stock_movements` kept as the immutable audit-grade source of truth. Sign convention is derived from `movement_type`; downward corrections are recorded as consumed/adjusted with notes rather than signed adjustments.
- **Row-locked inventory writes (Phase 3, M1):** movement recording takes a PostgreSQL `SELECT ... FOR UPDATE` row lock so concurrent movements cannot both apply against the same starting balance. The ledger remains the source of truth; a reconciliation endpoint recomputes balances from it to detect drift.
- **Thin services layer (introduced Phase 3, M1):** `app/services/inventory.py` holds the ledger sign/sum and reconciliation logic — the first domain logic extracted from route handlers. Routes keep request/auth/audit concerns; further Phase 3 milestones (finance, health) follow the same pattern.
- **Append-only records by convention:** `audit_logs` and `daily_site_logs` have no update/delete endpoints; `record_audit()` is explicit and transactional (committed atomically with the mutation) rather than ORM event hooks.
- **Application-level RBAC with shared project-visibility rules:** admin/procurement see all projects; supervisors/clients see only assigned ones, enforced per-endpoint via `project_access.assert_can_view_project`.
- **Access token in browser memory only; refresh token in localStorage** — chosen to reduce XSS lift of the access token (with the known trade-off documented in Security concerns).
- **Explicit rate limiting on auth only** (slowapi), isolated from application traffic.
- **explicit, exact-pinned dependencies** (no `~=` ranges) and a two-stage (runtime vs dev) requirements split.
- **Migrations committed as Alembic revisions** and applied at container startup (dev); `env.py` reads credentials from app settings as the single source of truth.