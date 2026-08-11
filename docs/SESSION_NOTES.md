# Session Notes — Phase 3 (M1 + M2 + M4 + M10 + M3 + M8 + M5 shipped; M6 planned)

**Session dates:** Aug 9–11, 2026. Branch `claude-development`.

See `CLAUDE.md`, `docs/ROADMAP.md` for durable context. This file records only
session-local details needed to resume.

## 1. What we accomplished

- Committed `d0a9e5c`/`0779e5d` (docs foundation + roadmap), then
  `1e046ec` (**feat: implement job costing and budget tracking** — M1+M2+M4),
  then `705cb05` (**feat: implement M10 project lifecycle & admin**).
- **M1 — inventory integrity:** row-locked `record_movement()` (`SELECT ... FOR UPDATE`),
  ledger-reconciliation service + `GET /projects/{id}/inventory/reconciliation`.
- **M2 — project-assignment management:** unique constraint on
  `(project_id, user_id)` + admin-only assign/unassign API + admin UI panel.
- **M4 — job costing:** `CostCode` enum on `job_costs`, job-cost CRUD, derived
  `Project.budget_spent` (= `SUM(job_costs)`, recomputed in-transaction),
  admin/proc-only `GET /projects/{id}/budget` roll-up, finance service,
  migration `c6d8e0f2a415`, 12 tests, `JobCostsPanel` frontend.
- **M10 — Project Lifecycle & Admin:** migration `d7e9f1a2b3c4` (unique
  `project_code`, lifecycle columns, `draft`+`archived` enum values); admin-only
  audited `activate`/`complete`/`archive`/`restore` endpoints; archived hidden
  from non-admins (404) and read-only; `select_project_code` retries on the
  unique-constraint race; seed gated behind `ICE_SEED_DEMO`; 12 tests.
  Suite 45 → **69 passing**.
- **M3 — Computed Project Health (Aug 11):**
  - Health is **derived on read** from source-of-truth rows (tasks, `job_costs`
    ledger, lifecycle status) — no health columns, no randomness (plan §3).
  - New migration `e8f2a3c5b7e4` (down_revision `d7e9f1a2b3c4`): creates
    `health_overrides` + `health_override_target`/`health_override_value`
    enums with partial unique index `(project_id, applied_to)
    WHERE revoked_at IS NULL`, and widens `audit_logs.action` varchar(20)→100
    (the 26-char `health_override_revoked` audit action exceeds varchar(20);
    see §3 decisions).
  - `app/models/health.py`: `HealthOverride` + target/value enums; adds
    `NOT_RATED` to `HealthStatus` (Python-side only — the legacy manual
    columns' DB enums are unchanged and never store it).
  - `app/services/health.py`: `rate_timeline` (SPI = progress vs elapsed;
    0.95/0.85 thresholds; early band; overdue only downgrades), `rate_budget`
    (consumption vs progress from the ledger; 5pp/15pp slips; over-budget floor;
    ≥95% near-completion cleanup; zero-spend ≤15% GREEN else NOT_RATED),
    `rate_safety` (always NOT_RATED), `rate_overall` (worst-of-rated + `basis`),
    `compute_health` (lifecycle + frozen + effective-vs-computed), and
    `load_health_contexts` (~3 batched queries for the whole roll-up).
  - API: `GET /projects/health` roll-up (declared **before** `/projects/{id}`,
    regression test guards this), `GET /projects/{id}/health`,
    `GET /POST /DELETE /projects/{id}/health-overrides` — all admin-only;
    creating an override revokes the prior unrevoked one in the same
    transaction (+ expiry handled in the app layer — Postgres forbids `now()`
    in partial-index predicates). Legacy health fields removed from
    `ProjectUpdate`; response serializer is role-scoped
    (`ProjectReadRestricted` for supervisor/client — no budget fields, M6 slice).
  - Frontend: `HealthDot` (NOT_RATED grey + reason tooltip), `ProjectCard` +
    `KpiStrip` take computed health + `canViewBudget`, `CommandCenter` health
    roll-up, new `ProjectHealthPanel` (admin override form + history), Project
    Detail budget gating by `canViewFinance`.
  - Seed P0 fix: demo `budget_spent` now equals `SUM(job_costs)` (3 rows each);
    `seed()` takes `(session_factory=AsyncSessionLocal, *, force=False)`.
  - Tests: `tests/test_health.py` 42 tests (SPI edges, budget verdict matrix
    incl. the green-always P0 regression, overall basis, lifecycle/frozen/
    archived, override expire/revoke/audit, RBAC + budget 403s, seed ledger
    invariant, route-shadowing regression). Suite **69 → 111 passing**.
    Frontend `tsc -b` + `vite build` + `oxlint` clean; ruff = only the 4
    pre-existing F401s; mypy = only the 12 pre-existing errors (none in new files).
- Verified budgets stay consistent across ARCHIVE/RESTORE and the health
  `budget` verdict now reads the ledger (0-cost projects show NOT_RATED, not
  GREEN).
- **M5 — Milestone Invoicing (Aug 11):** migration `g5b6c7d8e9f0` (new
  `billing_milestones` table + `billing_type`/`billing_milestone_status` enums;
  `invoices` gets `invoice_number` (unique), `billing_milestone_id`, notes +
  issuer/payer/canceller attribution, and the partial double-billing index
  `(billing_milestone_id) WHERE status <> 'CANCELLED'`).
  - `app/api/v1/invoicing.py`, `app/services/invoicing.py`, `app/schemas/invoice.py`
    (all new): admin-owned milestone config (one-rule invariant, duplicate-name
    409, frozen on COMPLETED projects, immutable once referenced by an
    invoice), terminal audited completion, server-side invoice amount derivation
    (`%` of `budget_total`, ROUND_HALF_UP; or fixed), per-project `INV-…-####`
    numbering under a project row lock, DRAFT→SENT→PAID + CANCELLED transitions
    (row-locked, audited, cancel frees the milestone), OVERDUE derived on read,
    M8 `Idempotency-Key` support, and lifecycle gating (ACTIVE-only generate;
    COMPLETED/ARCHIVED frozen). RBAC: procurement view-only, supervisors get no
    finance surface, clients see the restricted `InvoiceClientRead` shape on
    assigned projects (archived → 404).
  - Frontend `InvoicingPanel.tsx` (admin/proc: contract/invoiced/outstanding
    strip, add-milestone, complete + generate, issue/mark-paid/cancel) and
    `ClientInvoicesPanel.tsx` (read-only payment requests).
  - Tests: `tests/test_invoicing.py` (31) + `tests/test_migrations.py` (real
    Alembic upgrade/downgrade/replay on a scratch DB). The migration test
    caught a **pre-existing chain bug** — the initial migration
    `5d2e53a7df4e` never dropped its 5 enum types on downgrade (now fixed), so
    the chain is replayable. Suite **125 → 157 passing**; ruff clean in new
    files; mypy down to 10 (was 12).

## 2. Files changed in this session (M10 + M3 + M8 + M5 — NOT yet committed)

Backend (M5): `alembic/versions/g5b6c7d8e9f0_m5_invoicing.py` (new),
`alembic/versions/5d2e53a7df4e_initial_schema_users_projects_.py` (enum-drop fix),
`app/models/finance.py`, `app/models/__init__.py`, `app/api/v1/invoicing.py` (new),
`app/services/invoicing.py` (new), `app/schemas/invoice.py` (new),
`app/api/v1/router.py`, `tests/test_invoicing.py` (new),
`tests/test_migrations.py` (new).
Frontend (M5): `src/components/InvoicingPanel.tsx` (new),
`src/components/ClientInvoicesPanel.tsx` (new), `src/types/index.ts`,
`src/lib/api.ts`, `src/pages/ProjectDetail.tsx`.
Earlier-session files (M10 + M3, see prior entries):
`alembic/versions/d7e9f1a2b3c4_m10_project_lifecycle.py`,
`alembic/versions/e8f2a3c5b7e4_m3_health_overrides.py` (new),
`app/models/project.py`, `app/models/audit.py`, `app/models/health.py` (new),
`app/models/__init__.py`, `app/schemas/project.py`, `app/schemas/health.py`
(new), `app/api/v1/projects.py`, `app/api/project_access.py`,
`app/services/projects.py` (new), `app/services/health.py` (new), `app/seed.py`,
`tests/conftest.py`, `tests/test_project_lifecycle.py` (new),
`tests/test_health.py` (new).
Frontend (earlier): `src/types/index.ts`, `src/lib/api.ts`,
`src/pages/CommandCenter.tsx`, `src/pages/ProjectDetail.tsx`,
`src/components/ProjectCard.tsx`,
`src/components/HealthDot.tsx`, `src/components/KpiStrip.tsx`,
`src/components/ProjectHealthPanel.tsx` (new).
Docs: `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md`,
`docs/M3 — Computed Project Health: Implementation Plan.md` (new, planning),
`docs/M10 — Project Lifecycle & Admin: Implementation Plan.md` (new, planning).

## 3. Important decisions (M3, Aug 11)

- **Computed-on-read, never stored** (plan §3 option (a)): no denormalized
  health columns; verdicts are pure functions of committed rows + `today` +
  overrides. The deprecated manual columns stay in the DB (compat) but are no
  longer settable via `ProjectUpdate`, and `rate_*` never reads them.
- **Budget from the `job_costs` ledger only** — `Project.budget_spent` is the
  denormalized running total; the health service intentionally reads `SUM(...)`
  from the ledger so it can detect untracked spend (zero-spend + progress
  ⇒ NOT_RATED, not GREEN — this was a real P0: `spent==budget_spent==0` used
  to pass the "green-always" stability rule and report healthy).
- **Override semantics:** admin-only, audited
  (`health_override` / `health_override_revoked`), one active override per
  target (partial unique index), optional `expires_at`. Revoke restores the
  computed verdict — `effective_*` vs `computed_*` is the API contract.
- **`audit_logs.action` widened to varchar(100)** because the plan-named
  revocation action is 26 chars; the column only ever held create/update/delete
  before. Non-destructive length change shipped inside the M3 migration.
- **Partial-index predicate is `WHERE revoked_at IS NULL` only** — Postgres
  rejects volatile `now()` (STABLE) in index expressions, so expiry is enforced
  in `compute_health` (skip expired at read) and in the create flow (revoke all
  prior rows for the target, expired or not).
- **Health is admin-only** at every route (write and read roll-up); supervisor/
  client see per-project health through the role-scoped project serializer.
- **RBAC visibility first slice (M6 prep):** supervisors/clients get
  `ProjectReadRestricted` (no `budget`, no `budget_spent`) — a contract that M6
  extends; the client "view-only" portal is still future work.
- **Roll-up list order note:** `GET /projects` excludes ARCHIVED by default and
  for non-admins; `GET /projects/health` mirrors this.

## 4. Current project state

Phases 1 & 2 complete and intact; Phase 3 M1/M2/M4 committed (`1e046ec`), M10
committed (`705cb05`), M3 implemented but **uncommitted** (111/111 backend tests
pass against real Postgres; frontend `tsc`+`vite build` and `oxlint` clean; ruff
app+tests the same 4 pre-existing F401s, mypy the same 12 pre-existing errors —
nothing new introduced).
Dev DB is fully migrated: `a4b6c8d9e2f3` → `b5c7d9e1f203` → `c6d8e0f2a415` →
`d7e9f1a2b3c4` → `e8f2a3c5b7e4` (M3) all applied (verified Aug 11: `alembic_version
= e8f2a3c5b7e4`, `health_overrides` table + partial unique index
`uq_health_overrides_active_per_target WHERE revoked_at IS NULL`, `audit_logs.action`
now varchar(100)).

## 5. Current phase

Phase 3 — "Integrity, Operable RBAC, Admin Lifecycle & the Finance Pillar".

## 6. Current milestone

**M5 — Milestone Invoicing** is implemented and verified (backend tests + real
Alembic upgrade/downgrade on a scratch DB + frontend build/lint); next up is
**M6 — Client view-only scope** (the M3 serializer slice + M5 restricted
invoice shape are already in place).

## 7. Phase 3 remaining, in execution order

1. **M6 — Client view-only scope** (no budget fields for client role) — the M3
   serializer slice and M5 client invoice shape are a head start.
2. **M7 — Task date-order validation on update + dependency cycle detection.**
3. **M9 — Token security:** refresh rotation + server-side revocation.
4. **M11 — Google Sign-In** (NEW): Google authenticates only; ICE owns identity/
   role/assignments/permissions; never auto-grants ADMIN; inherits M9 sessions.
   Real-user rollout gate — after Phase 4 infra.

Phase 3 DB stubs still pending: unique `inventory_items (project_id, name)`,
`daily_site_logs (project_id, log_date)`; stock_movements/audit_logs list
indexes. Pre-existing debt (not in Phase 3 scope): ruff 4 F401 errors, mypy 10
errors (was 12 — M5 fixed the `finance.py` forward refs), no frontend tests.

## 8. Exact next action

1. **The running `backend` container is verified on M3 code** (deps + live reload
   of the docker-cp'd `app/`), M3 endpoints smoke-tested live:
   - Admin login → `GET /projects/health` roll-up (16 projects, health verdicts,
     `effective` per dimension), `POST .../health-overrides` (201; second create
     auto-revokes the first — single active per target holds), effective
     `budget` masked (green → red), `DELETE` (204) restores computed verdict,
     supervisor override → **403**, supervisor health roll-up/detail → 200
     (health status visible, but the restricted project serializer still hides
     dollar figures), audit trail records `health_override` +
     `health_override_revoked`.
2. **The committed Dockerfile got one line removed** (`# syntax=docker/dockerfile:1`)
   because the local daemon **cannot reach Docker Hub** (`docker pull
   docker/dockerfile:1` and base Python pulls hang → "DeadlineExceeded"); the
   built-in BuildKit frontend works and builds from cache. The container is thus
   running the OLD image + docker-cp'd code — ephemeral. When network to Docker
   Hub returns, `docker compose up -d --build backend` will produce the real new
   image (and the Dockerfile change is already in the repo).
3. Commit the M5 work when the owner asks.
4. Then **M6 — Client view-only scope** (finalize the client portal slice:
   already no budget figures; payment-request list shipped with M5).

## 9. Ambiguities / conflicts captured

- ~~Manual health PATCH vs computed health~~ — **RESOLVED (M3):** legacy
  columns removed from `ProjectUpdate`; verdicts move only through the audited
  `health-overrides` endpoint.
- ~~Override identity while expired rows linger~~ — **RESOLVED (M3):** partial
  unique index guards active rows; create revokes all prior rows for the target.
- ~~Safety dimension~~ — **RESOLVED (M3):** always NOT_RATED until a structured
  safety/quality data model exists; no color fabricated from free text.
- `Project.budget_spent` remains derived (M4 invariant); health reads the
  ledger, not the running total, so untracked spend surfaces as NOT_RATED.
- Future POs (Phase 5) map to projects — archived projects must stay read-only
  for all historical child records (UI freezes panels; API leaves mutation
  endpoints open to admin — flag if PO-posting must be blocked on ARCHIVED).
- Google email change / deactivation must map cleanly onto `google_sub` and the
  existing `is_active` cutoff. **Still open (M11).**

## 10. Unresolved questions / issues

- Postgres container **auto-stops** between sessions; restart with
  `docker compose up -d postgres` before running tests.
- Test env: pinned `requirements-dev.txt` was installed into the `py310_env`
  conda env so `pytest`/`ruff`/`mypy` run there
  (`/opt/miniconda3/envs/py310_env/bin/python -m pytest tests/ -q`).
- **Docker Hub unreachable from this machine** (`docker pull` hangs →
  DeadlineExceeded; host `curl` to dockerhub/pypi works). A real backend image
  rebuild (`docker compose up -d --build backend`) is blocked until the daemon
  regains registry access; the container currently runs docker-cp'd code, which
  is fine for dev verification but gets lost on stop/remove.
- **Migration bug found live:** `op.create_table` in SQLAlchemy 2.0.35 fires an
  unconditional, non-checkfirst `CREATE TYPE` for enum columns even with
  `create_type=False` (non-metadata enum path `_on_table_create`), so the first
  `alembic upgrade head` failed with `DuplicateObject` after the explicit
  checkfirst create ran. Resolved by creating the enums explicitly and adding the
  two enum columns via `op.add_column` (ALTER TABLE never re-creates the type).
  Tests don't catch this (conftest uses `create_all`, not alembic) — worth a
  migration-drift test.
- M11 owner decisions still required (see §8/§9 in previous notes).
- Deviating from roadmap UI guidance (replacing `alert()` with inline errors)
  applies to new components only; existing panels still use `alert()`.