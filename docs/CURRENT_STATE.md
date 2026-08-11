# Current State of the Software

**Document:** Actual implementation state of the ICE platform today
**Date:** August 11, 2026
**Basis:** Source-code inspection + verified runs (69 backend tests pass, live DB inspected)
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
- **Database:** PostgreSQL 16, 12 tables, 3 applied migrations.
- **Deployment:** Docker + docker-compose (local dev). Multi-stage non-root Dockerfile, 4 gunicorn workers, healthcheck, migrations run on container start.
- **Redis:** provisioned in compose, configured in settings, **never used by any code**.
- **Not present:** separate services layer, repositories, queues/workers, caching, file storage, notifications, external integrations, monitoring, CI/CD, IaC.

## 2. Implemented modules

| Module | Backend | Frontend | Notes |
|---|---|---|---|
| Authentication | `api/v1/auth.py`, `core/security.py`, `core/rate_limit.py` | `lib/auth-context.tsx`, `lib/api.ts`, `pages/Login.tsx` | JWT access (30m) + refresh (7d); bcrypt; login rate-limited 5/min |
| Users (admin CRUD) | `api/v1/users.py` | — | Admin-only; password policy 8 chars + 1 uppercase + 1 digit |
| Projects + health | `api/v1/projects.py`, `models/project.py`, `services/projects.py` | `CommandCenter.tsx`, `ProjectCard.tsx`, `KpiStrip.tsx`, `HealthDot.tsx`, `ProjectDetail.tsx`, `ProjectAssignments.tsx` | project lifecycle state machine (Phase 3 M10); health overrides + role-scoped serialization (Phase 3 M3) |
| Computed health | `models/health.py`, `models/project.py`, `services/health.py`, `schemas/health.py`, `api/v1/projects.py`, migration `e8f2a3c5b7e4` | `HealthDot.tsx`, `ProjectCard.tsx`, `KpiStrip.tsx`, `CommandCenter.tsx`, `ProjectHealthPanel.tsx` | Timeline (SPI) + Budget (consumption vs progress, from job-cost ledger) + Safety (always NOT_RATED) + Overall (worst-of-rated); audited admin-only override (Phase 3 M3) |
| Audit trail | `models/audit.py`, `middleware/audit.py`, `api/v1/audit.py` | — | Admin read endpoint only |
| Tasks / Gantt bars | `models/task.py`, `api/v1/tasks.py` | `ProjectTimeline.tsx` | Flat task list per project |
| Daily site logs | `models/site_log.py`, `api/v1/site_logs.py` | `DailySiteLogs.tsx` | Append-only create/read |
| Inventory ledger | `models/inventory.py`, `api/v1/inventory.py`, `services/inventory.py` | `InventoryPanel.tsx` | Items + row-locked signed stock-movement ledger; reconciliation report (`GET /projects/{id}/inventory/reconciliation`) |
| Finance (job costing) | `models/finance.py`, `api/v1/finance.py`, `services/finance.py`, `schemas/finance.py` | `JobCostsPanel.tsx` | `cost_code` enum; job-cost CRUD; `budget_spent` derived from `SUM(job_costs)`; budget roll-up report (Phase 3 M4) |
| Finance (invoicing) | `models/finance.py`, `api/v1/invoicing.py`, `services/invoicing.py`, `schemas/invoice.py`, migration `g5b6c7d8e9f0` | `InvoicingPanel.tsx`, `ClientInvoicesPanel.tsx` | Billing milestones (schedule of values) + milestone-driven invoices; server-side amount derivation; client read-only restricted shape (Phase 3 M5) |
| Seed/demo data | `seed.py` | — | 4 role users + 15 demo projects, gated behind `ICE_SEED_DEMO` (off in prod) |
| Project lifecycle | `models/project.py`, `api/v1/projects.py`, `services/projects.py`, migration `d7e9f1a2b3c4` | `CommandCenter.tsx`, `ProjectCard.tsx`, `ProjectDetail.tsx` | DRAFT→ACTIVE→COMPLETED→ARCHIVED state machine; archive/restore; auto `PRJ-YYYY-####` codes; `get_project_or_404` (Phase 3 M10) |

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
- **Finance schema:** `job_costs`, `invoices` tables migrated (invoices scaffold; the M5 migration `g5b6c7d8e9f0` turned them into the real ledger).
- **Shared helpers:** `project_access.py` extracted and used by all project-scoped routes.
- **Tests:** task, site-log, and inventory suites (33 total backend tests, all pass against real Postgres).

## 4b. Phase 3 completed functionality

- **Finance (P3 M4):** Job-costing landed — `cost_code` enum (`foundation`…`other`), `GET/POST /projects/{id}/job-costs` + `PATCH/DELETE .../{cost_id}` (admin/procurement read **and** write — cost line items are budget data and are 403 for clients/supervisors), and `GET /projects/{id}/budget` (admin/proc roll-up: total / spent / remaining / by-cost-code). `Project.budget_spent` is now **derived** from `SUM(job_costs.amount)` in the same transaction as every mutation (denormalized running total, like `quantity_on_hand`), and job-cost mutations lock the project row (`SELECT ... FOR UPDATE`, the M1 inventory pattern) so concurrent writes can't drift the total from the ledger — the acceptance invariant `budget_spent == SUM(job_costs)` holds. Finance service follows the Phase 3 thin-services pattern (`app/services/finance.py`, pure domain math). Invoices remain schema-only (M5).
- **Testing (P3 M4):** `tests/test_finance.py` — 12 tests covering create/update/delete budget recompute, roll-up split, supervisor write-403, client+supervisor read-403, client budget-403, amount validation, 404s, and a concurrent-WRITE row-lock regression test (no lost budget update).
- **Project Lifecycle & Admin (P3 M10):** status becomes a real state machine (`draft|planning|active|on_hold|completed|archived`). `POST /projects` (admin) auto-generates a unique `PRJ-YYYY-####` `project_code` and creates the project as **DRAFT**. Admin-only transition endpoints (`POST /projects/{id}/activate|complete|archive|restore`) validate the legal transition from the project's current status (400 otherwise), set lifecycle timestamps + actor ids, and audit (activate/complete/archive/restore actions) atomically with the change:
  - `activate` (DRAFT/PLANNING/ON_HOLD→ACTIVE), `complete` (ACTIVE→COMPLETED, sets `percent_complete=100` + `completed_at/by`), `archive` (ACTIVE|COMPLETED→ARCHIVED, sets `archived_at/by`; rejects DRAFT/PLANNING/ON_HOLD), `restore` (ARCHIVED→ACTIVE, or →COMPLETED when it was completed before archiving; sets `restored_at/by`).
  - `ProjectUpdate` no longer accepts `status` (and `budget_spent` is derived from `job_costs`, never client-settable) — status changes only through the transition endpoints.
- **Archive visibility (P3 M10, hardened):** `get_project_or_404` and `list_projects` exclude ARCHIVED from non-admin results — admin/procurement see archived (listing requires `?include=archived`), supervisors/clients get **404** (archived, not 403, so archived projects can't be probed/leaked). Archived projects are read-only for **every** writer: the lifecycle transition endpoints are the deliberate exception, and every other write path (project PATCH, assignment grant/revoke, tasks, site logs, inventory items/movements, job costs) rejects writes to an ARCHIVED project via the shared `assert_project_writable()` guard in `app/api/project_access.py` (403 for admin/procurement after visibility is resolved; supervisors/clients still get 404). The UI renders the detail page read-only until restored.
- **Transition/archive concurrency (P3 M10, hardened):** `_transition` and `restore` now load the project with a PostgreSQL row lock (`SELECT ... FOR UPDATE`, the existing M1/M4 pattern) held to commit, so concurrent transitions serialize: only one lifecycle decision is made against a given state and the audit chain can't contradict itself. `create_project` now regenerates the `project_code` and retries (up to 5 attempts) when the DB unique constraint fires on a concurrent max()+1 collision, returning a clean 409 instead of an avoidable 500.
- **Seed gating (P3 M10):** `seed.py` demo users/projects only load when `ICE_SEED_DEMO=true` (dev/local), keeping prod empty.
- **Testing (P3 M10):** `tests/test_project_lifecycle.py` — 12 tests covering the full DRAFT→ACTIVE→COMPLETED→ARCHIVED→restore chain, admin-only enforcement (403 for supervisor/procurement/client on all four transitions), invalid transitions rejected 400 (`activate` on non-DRAFT, default-DRAFT `transition`, archive of PLANNING/ON_HOLD), archive filtering (`?include=archived`, default excludes), archived 404-for-non-admin while sibling assigned projects stay visible, audit events recorded per transition with correct changes/actor, `project_code` auto-generation + `PRJ-2026-####` uniqueness/seq-collision retry, and descendants (tasks/site logs/inventory/job-costs) surviving archive/restore round-trip with `budget_spent` invariant intact.
- **Computed Health (P3 M3):** health is now derived deterministically on read from source-of-truth rows — **no health columns, no randomness**; identical data + `today` + overrides ⇒ identical verdict. `Project.health_state` is a dataclass assembled by `app/services/health.py` (`compute_health` + batched `load_health_contexts`, ~3 queries regardless of roll-up size):
  - **Timeline** = SPI from real signals: `percent_complete` vs the fraction of schedule elapsed (`start_date`→`target_end_date`). GREEN ≥ 0.95 SPI, AMBER ≥ 0.85, below RED. Early band (<5% elapsed) and "no progress yet" report GREEN; zero/negative-duration schedules and "not yet started" report NOT_RATED. A large share of overdue tasks only ever **downgrades** the verdict (tested: 0.20/0.40 fractions to AMBER/RED).
  - **Budget** = consumption vs physical progress, straight from the M4 `job_costs` ledger (`SUM`), never the denormalized `budget_spent` column. Spent may lead progress ≤ 5pp ⇒ GREEN, ≤ 15pp ⇒ AMBER, above ⇒ RED; over-budget floors at AMBER; ≥95% complete treats small overruns as GREEN. Zero spend ≤15% progress ≈ GREEN, otherwise NOT_RATED ("budget may be untracked") — so a 0-cost project no longer shows as healthy just because *spent == budget_spent*.
  - **Safety** = always NOT_RATED ("no safety/quality data captured yet") — there is no structured safety data model, so no color is fabricated from free-text issues or the deprecated manual column.
  - **Overall** = worst-of-*rated* dimensions, with the exact `basis` list exposed (unrated dims never drag/lift the verdict). `rated` is the contract for "is there enough data to claim a color".
  - **Lifecycle:** DRAFT/PLANNING never compute ("not yet in execution"), ON_HOLD → NOT_RATED, ACTIVE computes, COMPLETED keeps its verdict with `frozen: true`, ARCHIVED reports all NOT_RATED with `frozen: true` + "Archived projects do not compute new health."
  - **Audited admin override:** admin-only `GET/POST/DELETE /projects/{id}/health-overrides` set/revoke a manual verdict per target (overall/timeline/budget/safety, GREEN/AMBER/RED only) with optional `expires_at`. A partial unique index `(project_id, applied_to) WHERE revoked_at IS NULL` guarantees precedence is well-defined; creating a new override revokes the previous unrevoked one for that target in the same transaction; revokes delete the effective override and never the computed verdict (which remains queryable via `detail`/`computed`, only `effective_*` is masked). The legacy manual PATCH health fields were **removed** from `ProjectUpdate` — verdicts move only through this endpoint.
  - **RBAC slice (M6 prep):** project response serializer is role-scoped — admin/procurement see full budget (`budget` block), supervisors get the `ProjectReadRestricted` shape (no `budget`, no `budget_spent`), and (M6) clients get the even tighter `ProjectClientRead` shape — the lean first slice of the client view-only contract.
  - **Testing (P3 M3):** `tests/test_health.py` — 42 tests: SPI/edge unit tests, budget-vs-progress verdict matrix incl. the `green-always` P0 bug (6 outcomes), overall worst-of-rated + basis, lifecycle/frozen + archived flat, override CRUD + expire/revoke + audit actions (`health_override`/`health_override_revoked`), RBAC (role-scoped visibility, client budget 403s, archive exclusion), seed ledger invariant (`budget_spent == SUM(job_costs)`), and a route-registration regression (new `GET /projects/health` must be declared before `/projects/{project_id}`). Full suite **69 → 111 passing**. `audit_logs.action` was widened `varchar(20)→varchar(100)` (migration `e8f2a3c5b7e4`) so the 26-char `health_override_revoked` action fits.
  - **Seed P0 fix:** demo projects were created with `budget_spent` that did **not** equal `SUM(job_costs)` — `seed()` now writes 3 job-cost rows per project summing exactly to the budget, and takes `(session_factory=AsyncSessionLocal, *, force=False)`.
- **Idempotency keys (P3 M8):** server-side `Idempotency-Key` support for POST mutations, built as a reusable dependency (`get_idempotency_guard`, `app/api/deps.py`) + service (`app/services/idempotency.py`) + a new `idempotency_records` claim ledger (migration `f3a4b5c6d7e8`). **Protected endpoints:** `POST /projects/{id}/job-costs`, `POST /projects/{id}/inventory/{item_id}/movements`, `POST /projects/{id}/site-logs`, and `POST /projects` (create):
  - **Claim ledger:** each request carrying the header inserts a claim row (status `in_progress`) into the **same transaction** as the mutation it protects, so claim + business rows + audit + response snapshot commit atomically. A successful handler finalizes the claim to `completed` with the exact response body before its `db.commit()`. A failed attempt rolls the whole transaction back, leaving the key **free for a safe retry** (verified: below-zero movement → 400, then the same key succeeds).
  - **Retry = replay, not re-execute:** the same key + same request replays the stored response verbatim (same resource id, budget/stock untouched). The request fingerprint canonicalizes method + route template + resolved path params + sorted JSON body, so reusing a key for a *different* request (different body or different project) is a 409, never a wrong replay. Keys are namespaced per user (`actor_id`) and per operation (route template).
  - **Concurrency:** the DB unique index `(actor_id, operation, idempotency_key)` is the enforcement point — a concurrent same-key INSERT blocks until the winner's transaction commits or aborts, so exactly one business operation executes and the loser replays the winner's response (verified with per-request-session concurrent requests).
  - **Expiry:** claims live 24h; reusing an expired key returns 409 with "issue a new key" — deliberately safer than re-executing, so a stale retry can never silently duplicate a record.
  - **create_project interplay:** the project-code IntegrityError retry loop rolls the claim back too, so the handler re-claims the key before retrying (`idem.reclaim`) — idempotency survives code-collision regeneration.
  - **Deliberately NOT protected (and why):** lifecycle transitions (state-machine guarded — a retry can't double-mutate), assignments (unique-constrained → 409 on duplicate), all PATCH/DELETE (naturally idempotent). **Deferred (1-line enable later):** POST tasks, health-overrides, users — low corruption risk, infra already shared.
  - **Frontend gap:** the SPA does not yet generate `Idempotency-Key` headers. A per-request random key adds no dedupe (retries get fresh keys); real double-submit protection needs the client to hold one key per logical operation and reuse it across retries — a frontend follow-up. The backend accepts requests with or without the header, so nothing breaks meanwhile.
  - **Testing (P3 M8):** `tests/test_idempotency.py` — 14 tests covering verbatim replay on all four protected endpoints, 409 on body/project divergence, key freed after a failed attempt, per-user + per-operation key namespacing, expired/oversized keys, and a true concurrent same-key test (both 201, same resource, one ledger row). Full suite **111 → 125 passing**.
- **Milestone invoicing (P3 M5):** the billing/revenue surface — deliberately independent of the job-cost ledger (expenditure). An admin builds a schedule-of-values (`GET/POST /projects/{id}/billing-milestones`, `PATCH .../{milestone_id}`, admin-only; procurement is view-only) where each milestone carries **exactly one** rule (`billing_type=percentage` → `billing_percentage`, or `fixed_amount`), validated at the schema + invariant level. `POST .../{milestone_id}/complete` is terminal and audited; **COMPLETED is the eligibility gate** for generating an invoice.
  - **Invoice generation (`POST /projects/{id}/invoices`):** the amount is **derived server-side** from the milestone rule × `Project.budget_total` (`ROUND_HALF_UP` on percentage math) — clients never supply money values. `invoice_number` auto-sequences per project (`INV-{PROJECT_CODE}-{seq}`, project row-locked so numbering serializes), `due_date` defaults to +30 days, and the result starts as DRAFT. Double-billing is guarded twice: an app-level 409 and a **partial unique index** `(billing_milestone_id) WHERE status <> 'CANCELLED'` (DB backstop for concurrent no-key requests — the loser gets a clean 409, verified). The shared M8 `Idempotency-Key` dependency protects the endpoint (retry replays the stored invoice).
  - **Transitions (admin-only, row-locked, audited):** DRAFT→SENT (`issue`), SENT→PAID (`mark-paid`), DRAFT|SENT→CANCELLED (`cancel`, terminal). A cancelled invoice **frees** its milestone for a re-issue (numbering continues). OVERDUE is **derived on read** (SENT + due_date passed) — never stored, so it can't go stale.
  - **Lifecycle gating:** milestone config is frozen on COMPLETED projects; invoice creation/transitions require an ACTIVE project; ARCHIVED is read-only everywhere via the shared `assert_project_writable()` guard. A milestone referenced by a non-cancelled invoice is immutable (its rule can't desync the paper trail).
  - **RBAC:** admin owns everything; procurement reads full shapes but can't create/transition; supervisors get **no** finance surface (403); clients see **only** their assigned projects' invoices in the restricted `InvoiceClientRead` shape (no notes / billing rules / budget figures), archived → 404.
  - **Frontend:** `InvoicingPanel.tsx` (admin/procurement — contract/invoiced/outstanding strip, add-milestone form, complete + generate-invoice actions, invoice list with issue / mark-paid / cancel) and `ClientInvoicesPanel.tsx` (clients — read-only payment-request list with overdue flags).
  - **Testing:** `tests/test_invoicing.py` — 31 tests covering milestone one-rule validation + duplicate-name 409, terminal completion, invoice amount derivation + rounding, per-project number sequencing, double-bill 409 + cancel-and-reissue, idempotent replay, transition state guards, overdue derivation, full RBAC matrix (incl. client restricted shape + archived-404), audit rows for every action, and a concurrent no-key double-billing race (`[201, 409]`, exactly one invoice). `tests/test_migrations.py` runs the **real Alembic chain** on a scratch DB (upgrade head → verify tables → downgrade base → verify drop → upgrade head again) — this surfaced and fixed a **pre-existing bug**: the initial migration never dropped its 5 enum types on downgrade, making the chain non-replayable (now fixed in `5d2e53a7df4e`). Full suite **125 → 157 passing**.
- **Client portal boundary (P3 M6):** the CLIENT role is now a first-class, strictly read-only persona with a **server-enforced** portal contract. `ProjectClientRead` (`app/schemas/project.py`) is the only project shape a client ever receives — name/code/site/client/schedule/status/progress plus `completed_at`; everything internal is stripped (budget figures, the deprecated manual health columns, lifecycle attribution `created_by/completed_by/archived_by/restored_by`, archive/restore bookkeeping, internal `created_at`/`updated_at`). `_serialize_project(project, user.role)` in `app/api/v1/projects.py` routes the role to `ProjectRead` (admin/proc via `full_view_roles`) / `ProjectReadRestricted` (supervisor) / `ProjectClientRead` (client):
  - **Health is not a client surface:** `GET /projects/health` and `GET /projects/{id}/health` return **403** for clients via the shared `assert_not_client()` guard (`app/api/project_access.py`) — computed health (colors, reasons, basis) is an internal management signal; the client portal shows progress instead. Supervisors keep full health read access (the health payload never carries money).
  - **Inventory is not a client surface:** item lists and the stock-movement ledger are 403 for clients (`assert_not_client` in `app/api/v1/inventory.py`) — unit costs and stock levels are procurement data.
  - **Invoices — issued only:** the client's invoice list **filters out DRAFT** invoices and `get_invoice` returns **404** for DRAFT (their existence is never leaked); SENT/PAID/CANCELLED stay visible in the restricted `InvoiceClientRead` shape (previously the client list exposed DRAFTs).
  - **Writes:** clients are read-only in this phase — the existing role-gated write endpoints (tasks/site logs admin+supervisor, inventory/job-costs admin+procurement, milestones/invoices admin) already reject with 403.
  - **Frontend:** the SPA is client-aware — `CommandCenter` skips the health roll-up for clients (no 403 noise), hides the "Show archived" toggle, and renders a site-count-only `KpiStrip` (`showHealth` flag); `ProjectCard` drops the health-dot row and budget badge for clients; `ProjectDetail` never fires the health query for clients and hides the health panel, `InventoryPanel` and the archived-attribution row, keeping timeline + daily logs + `ClientInvoicesPanel`. `Project` fields the client shape omits are now optional in `frontend/src/types/index.ts`, with `?? 0` guards where money rows render for admin/proc.
  - **Testing (P3 M6):** `tests/test_client_portal.py` — 7 tests pinning the tight client project shape on list+detail, own-projects-only listing, health 403 (roll-up + single), inventory 403 (items + movements), DRAFT-invoice hidden/404 → SENT visible in the restricted shape, unassigned-project invoice 403, and read-only writes (task/milestone/inventory 403). `test_health.py` updated: supervisors keep health, clients now assert 403. Full suite **157 → 164 passing**.

## 5. Partially implemented functionality

- **Dynamic Gantt:** tasks and dependency column exist, but changing a task date does **not** shift downstream tasks, and there are **no vendor notifications**. The frontend never sends `depends_on_id`.
- **Health indicators:** Timeline and Budget are now **computed** on read (Phase 3 M3) from real schedule + job-cost data, with an audited admin-only override; the legacy manual `timeline_health`/`budget_health`/`safety_health` columns are deprecated and no longer settable via `ProjectUpdate`. Safety stays NOT_RATED until a structured safety/quality data model exists.
- **Low-stock alerts:** UI flags `quantity_on_hand <= reorder_threshold` only; there is no 7-day scheduled-demand calculation and no alerting mechanism.
- **Daily site logs:** text fields fully work; the mandatory "5 photos + voice-to-text" capture does not — `photo_urls` is always an empty list.
- **Audit trail:** covers CRUD on users/projects/tasks/logs/inventory but not login/refresh events; `ip_address` is never populated.
- **Client experience:** the Client role can log in and view only their assigned projects (tight `ProjectClientRead` shape — no budgets, no health, no lifecycle attribution), their schedule/timeline, daily site logs, and issued payment requests (P3 M5 restricted shape; DRAFT invoices hidden). Computed health, the inventory/procurement ledger and all write endpoints are 403 — but this is not yet the PRD's full view-only photo portal.
- **Finance:** job-costing and milestone invoicing both exist (P3 M4 + M5, see §4b); only external-accounting sync remains (blocked on a provider/OAuth decision, per repo notes).

## 6. Known bugs

- **Concurrent stock movements can lose updates — RESOLVED (Phase 3, M1):** `record_movement` now locks the item row (`SELECT ... FOR UPDATE`) so simultaneous movements serialize instead of both deciding against the same starting balance. A concurrency test fires two parallel consumptions (both persist, on-hand = 40 after 2×30 from 100) and `GET /projects/{id}/inventory/reconciliation` recomputes each item's balance from the ledger to surface any legacy drift. (`api/v1/inventory.py`, `services/inventory.py`)
- **Task `PATCH` skips date-order validation:** create validates `end_date >= start_date`; update does not — a malformed task (end before start) can be saved via `PATCH`. (`schemas/task.py`)
- **Task dependency cycles allowed:** `depends_on_id` can be set to form a self-reference or cycle; not checked on create or update.
- **Duplicate-ish data allowed — partially RESOLVED:** duplicate `project_assignments` rows are now impossible (unique constraint + API returns 409, Phase 3 M2); duplicate inventory item names per project, and multiple daily site logs per day, still have no uniqueness constraints.
- **`uuid.UUID(user_id)` can raise `ValueError` -> 500** in `deps.py:45` and `auth.py:55` when a token carries a non-UUID subject (low exploitability, tokens are signed).
- **Concurrent lifecycle transitions can race — RESOLVED (Phase 3 M10 hardening):** `activate`/`complete`/`archive`/`restore` now take a `SELECT ... FOR UPDATE` row lock on the project (via `get_project_for_update`) in the same transaction as the transition, so two simultaneous transitions serialize on the project row and only one passes the status guard per committed state.
- **Backend lint/type failures:** `ruff check app tests` reports 4 unused-import (F401) errors (all pre-existing files, untouched); `mypy app` reports 10 errors (broken `Mapped["Project"]` forward references in `inventory.py`/`site_log.py`/`task.py`, config args, jose/passlib stubs — the same pattern in `models/finance.py` was fixed by importing `Project` during M5).
- **`ip_address` on audit entries is always NULL** — the parameter exists but is never passed.

## 7. Technical debt

- **No services/repositories layer:** route handlers mix dependency injection, authorization, validation, business logic, DB access, and audit in single functions.
- **Duplicated audit-pattern code:** the "build changes dict from `model_dump(exclude_unset=True)`" pattern is copy-pasted in `users.py:79`, `projects.py:91`, `tasks.py:100`, `inventory.py:111`.
- **Dead code / unused dependencies:** `redis` and `tenacity` in requirements (never used); `GCP_PROJECT_ID` / `GCS_BUCKET_NAME` config stubs; legacy manual `timeline_health`/`budget_health`/`safety_health` columns (deprecated by M3, no longer API-settable, kept for DB compat).
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

- **Backend tests: 157, all passing** against real Postgres (verified on Aug 11, 2026). Files: test_auth (9), test_users (8), test_tasks (7), test_site_logs (4), test_inventory (9 — incl. row-lock concurrency, ledger-reconciliation match/mismatch, reconciliation RBAC), test_projects (8 — assignment API admin/RBAC/duplicate/isolation), test_finance (12 — job-cost CRUD, budget recompute, roll-up split, RBAC, validation, concurrent-WRITE row lock; Phase 3 M4), test_project_lifecycle (12 — lifecycle transitions, admin-only, invalid transitions, archive filtering + 404 non-admin visibility, audit, codegen uniqueness/collision, archive/restore descendant + budget invariant; Phase 3 M10), test_health (42 — SPI/edge rates, budget verdict matrix + green-always regression, overall basis, lifecycle/frozen/archived, override expire/revoke + audit, RBAC visibility + budget 403s, seed ledger invariant, route-shadowing regression; Phase 3 M3), test_idempotency (14 — retry replay, 409 on request divergence, key freed after failure, per-user/per-operation namespacing, expired/oversized keys, concurrent same-key single-execution; Phase 3 M8), test_invoicing (31 — milestone one-rule validation + duplicate-name 409, terminal completion, server-side amount derivation + ROUND_HALF_UP, invoice-number sequencing, double-bill 409 + cancel-reissue, idempotent replay, transition guards, overdue derivation, RBAC incl. client restricted shape + archived-404, audit per action, concurrent no-key double-billing race; Phase 3 M5), test_migrations (1 — real Alembic upgrade/downgrade/replay on a scratch DB; surfaced + verified the enum-drop fix in the initial migration).
- **Coverage: ~75%** overall (pytest-cov). Lowest areas: inventory `api/v1/inventory.py` 39%, `projects.py` 42%, `tasks.py` 42%.
- **Frontend tests: none** (no vitest/RTL config or tests).
- **Missing critical tests:** project CRUD/PATCH RBAC/budget-validation edge cases beyond the lifecycle/health suites; client read-isolation (archived-404 is covered; assigned-client non-archived read is not); audit endpoint (`/audit/logs`) untested; lifecycle concurrency race and Google auth (M11) not yet written.
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
- **Project Lifecycle & Admin — IMPLEMENTED (Phase 3 M10):** `project_code` auto-generation (`PRJ-YYYY-####`), the DRAFT→ACTIVE→COMPLETED→ARCHIVED lifecycle with `restore`, lifecycle actor/timestamps + auditing, archive visibility (non-admins get 404 on archived projects), demo-seed gating (`ICE_SEED_DEMO`), read-only enforcement for ARCHIVED across every write path, row-locked transitions/restore, and retry-on-collision project-code generation are all in (§4b). No DELETE endpoint exists for any state (by design — nothing is hard-deletable, soft-lifecycle only).
- **Google Sign-In — PLANNED (Phase 3 M11):** only email/password auth exists; no OAuth2/OIDC provider, no `google_sub`/account linking, no admin invitation without a preset password (user creation requires a password today), no server-side session/revocation infrastructure (see Security concerns), and no audit of auth events. Google will authenticate **only** — ICE retains identity, role, assignments, and permissions.
- **Finance**: job-costing and milestone invoicing are implemented (P3 M4 + M5, see §4b); **external-accounting sync** (QuickBooks/Xero) is not — the `external_ref`/`external_sync_status` columns are placeholders, blocked on a provider/OAuth decision per repo notes.
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
- **Idempotency via a transactional claim ledger (Phase 3, M8):** the `idempotency_records` table is both the dedupe mechanism and the source of replay responses. The claim INSERT, the protected mutation, its audit row, and the response snapshot commit in one transaction; a DB unique index `(actor_id, operation, idempotency_key)` serializes concurrent same-key requests. App-level claim lookups resolve retries *before* touching the business rows, so a replay never re-runs business logic. Expired keys are refused (409) rather than re-executed — bias toward refusing a stale retry over risk of a silent duplicate.
- **Application-level RBAC with shared project-visibility rules:** admin/procurement see all projects; supervisors/clients see only assigned ones, enforced per-endpoint via `project_access.assert_can_view_project`.
- **Access token in browser memory only; refresh token in localStorage** — chosen to reduce XSS lift of the access token (with the known trade-off documented in Security concerns).
- **Explicit rate limiting on auth only** (slowapi), isolated from application traffic.
- **explicit, exact-pinned dependencies** (no `~=` ranges) and a two-stage (runtime vs dev) requirements split.
- **Migrations committed as Alembic revisions** and applied at container startup (dev); `env.py` reads credentials from app settings as the single source of truth.