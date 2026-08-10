# Session Notes — Phase 3 (M1 + M2 + M4 + M10 shipped; M11 planned)

**Session dates:** Aug 9–11, 2026. Branch `claude-development`.

See `CLAUDE.md`, `docs/ROADMAP.md` for durable context. This file records only
session-local details needed to resume.

## 1. What we accomplished

- Committed `d0a9e5c`/`0779e5d` (docs foundation + roadmap), then
  `1e046ec` (**feat: implement job costing and budget tracking** — M1+M2+M4).
- Planned Phase 3 and revised the roadmap (Aug 10) to add **M10 — Project
  Lifecycle & Admin** and **M11 — Google Sign-In** before the rest of Phase 3.
- **M1 — inventory integrity:** row-locked `record_movement()` (`SELECT ... FOR UPDATE`),
  ledger-reconciliation service + `GET /projects/{id}/inventory/reconciliation`.
- **M2 — project-assignment management:** unique constraint on
  `(project_id, user_id)` + admin-only assign/unassign API + admin UI panel.
- **M4 — job costing:** `CostCode` enum on `job_costs` (replaces the unused
  free-text `category` column), job-cost CRUD (`GET/POST/PATCH/DELETE
  /projects/{id}/job-costs`), derived `Project.budget_spent` (= `SUM(job_costs)`,
  recomputed in-transaction on every mutation), admin/proc-only
  `GET /projects/{id}/budget` roll-up, finance service (`app/services/finance.py`),
  migration `c6d8e0f2a415`, 12 tests, `JobCostsPanel` frontend. Suite grew
  45 → **57 passing**.
- **M10 — Project Lifecycle & Admin (Aug 11):**
  - Migration `d7e9f1a2b3c4` adds unique `project_code`, `created_by`,
    `completed_at/by`, `archived_at/by`, `restored_at/by`, extends
    `project_status` enum with `draft` + `archived` (existing values kept).
  - `app/services/projects.py` — `generate_project_code()` (`PRJ-YYYY-####`,
    max-seq + unique-constraint retry), thin-services pattern.
  - `POST /projects` (admin) now auto-generates the code and creates **DRAFT**;
    `ProjectUpdate` no longer accepts `status` or `budget_spent`.
  - Admin-only, audit-coupled transition endpoints: `activate`
    (DRAFT/PLANNING/ON_HOLD→ACTIVE), `complete` (ACTIVE→COMPLETED, sets 100% +
    `completed_at/by`), `archive` (ACTIVE/COMPLETED→ARCHIVED, sets `archived_at/by`;
    rejects DRAFT/PLANNING/ON_HOLD), `restore` (ARCHIVED→COMPLETED if it was
    completed before archiving else ACTIVE, sets `restored_at/by`).
  - Archive visibility: non-admins get **404** on archived projects (existence
    does not leak); `GET /projects` excludes ARCHIVED unless admin/proc pass
    `?include=archived`. `get_project_or_404` + `can_access_archived` in
    `app/api/project_access.py`. `get_project_or_404` now used by every
    project-scoped route in `api/v1/projects.py` (was ad-hoc per route).
  - Seed gating resolved: demo users/projects load only when
    `ICE_SEED_DEMO=true` (env-flag only, no per-row `is_demo` column).
  - Frontend: `ProjectStatus`/`Project` types extend (`project_code`, lifecycle
    fields, `draft`/`archived`); Command Center admin "New site" modal + "Show
    archived" toggle; ProjectCard shows `project_code` + per-status badge tone;
    ProjectDetail lifecycle action menu (admin, legal-from-status only) +
    archival banner + lifecycle date rows; child panels freeze (read-only) when
    archived.
  - Tests: `tests/test_project_lifecycle.py` — 12 tests (transitions chain,
    RBAC 403s, invalid-transition 400s, archive filtering, archived-404 vs
    assigned visibility, audit rows, codegen uniqueness/seq-retry, descendants
    + budget invariant across archive/restore). Suite **57 → 69 passing**.
- Verified budgets stay consistent across ARCHIVE/RESTORE: `budget_spent ==
  SUM(job_costs)` invariant holds after archive → restore round-trip.

## 2. Files changed in this session (M10 — implemented, NOT yet committed)

Backend: `alembic/versions/d7e9f1a2b3c4_m10_project_lifecycle.py` (new),
`app/models/project.py`, `app/schemas/project.py`, `app/api/v1/projects.py`,
`app/api/project_access.py`, `app/services/projects.py` (new), `app/seed.py`,
`tests/conftest.py`, `tests/test_project_lifecycle.py` (new).
Frontend: `src/types/index.ts`, `src/lib/api.ts` (project helpers),
`src/pages/CommandCenter.tsx`, `src/pages/ProjectDetail.tsx`,
`src/components/ProjectCard.tsx`.
Docs: `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md`,
`docs/M10 — Project Lifecycle & Admin: Implementation Plan.md` (new, planning).

## 3. Important decisions

- M1 first (correctness bug, independent, low blast radius), then M2
  (unlocks real RBAC), then M4 (job costing), then M10 (admin lifecycle).
- Reconciliation is a **report-only** endpoint (admins fix drift via an ADJUSTED
  movement), not an auto-correcting job.
- Thin `services/` layer pattern (`finance.py`, `projects.py`) for Phase 3
  domain logic; routes stay auth/audit plumbing.
- **M10 decisions (Aug 11):**
  - Lifecycle transitions are **admin-only, audited, dedicated endpoints**
    (`activate`/`complete`/`archive`/`restore`); `PATCH /projects` refuses
    `status`/`budget_spent` so status moves only through the state machine.
  - **Seed gating = env flag only** (`ICE_SEED_DEMO`); no `is_demo` column —
    the implementation-plan option (a) "env-flag only" was chosen.
  - **Enum extended, not replaced:** `planning|active|on_hold|completed` kept,
    `draft|archived` appended → no destructive enum change.
  - ARCHIVED is a soft terminal state: hidden from non-admins (404, not 403),
    read-only/frozen in UI, assignments endpoints reject writes, never DELETE.
  - Transitions are read-modify-write **without** `SELECT ... FOR UPDATE` — noted
    as a Known-limitation/hardening item (M1/M4 already row-lock; same fix here).
- **M10 before M3/M5** (health + invoicing operate on a lifecycle-aware project
  universe; only ACTIVE compute health / generate invoices).
- **M9 before M11** (refresh rotation + revocation + deactivation cutoff must
  exist before Google is trusted with sessions).
- **M6 before real clients on Google** (role-scoped contract so Google-linked
  clients never see budget fields).

## 4. Current project state

Phases 1 & 2 complete and intact; Phase 3 M1/M2/M4 committed (`1e046ec`), M10
implemented but **uncommitted** (69/69 backend tests pass against real Postgres;
frontend `tsc`+`vite build` and `oxlint` clean; ruff app+tests 4 pre-existing
F401s, mypy 12 pre-existing errors — nothing new introduced).
Migrations `a4b6c8d9e2f3` + `b5c7d9e1f203` + `c6d8e0f2a415` applied to the dev DB;
migration `d7e9f1a2b3c4` (M10) is a new revision on HEAD, not yet applied.

## 5. Current phase

Phase 3 — "Integrity, Operable RBAC, Admin Lifecycle & the Finance Pillar".

## 6. Current milestone

**M10 — Project Lifecycle & Admin** is implemented; next up is **M3 — computed
health** (was "M5 invoicing").

## 7. Phase 3 remaining, in execution order

1. **M3 — Computed project health** (+ audited manual override) over ACTIVE only.
2. **M5 — Invoicing** (milestone → invoice generation) gated to ACTIVE.
3. **M6 — Client view-only scope** (no budget fields for client role).
4. **M7 — Task date-order validation on update + dependency cycle detection.**
5. **M8 — Idempotency keys on movement/site-log/invoice POSTs.**
6. **M9 — Token security:** refresh rotation + server-side revocation.
7. **M11 — Google Sign-In** (NEW): Google authenticates only; ICE owns identity/
   role/assignments/permissions; never auto-grants ADMIN; inherits M9 sessions.
   Real-user rollout gate — after Phase 4 infra.

Phase 3 DB stubs still pending: unique `inventory_items (project_id, name)`,
`daily_site_logs (project_id, log_date)`; `invoices` milestone mapping (M5);
stock_movements/audit_logs list indexes; lifecycle-transition row lock (hardening).
Pre-existing debt (not in Phase 3 scope to fix unilaterally): ruff 4 F401 errors,
mypy 12 errors, no project CRUD/PATCH-RBAC test coverage beyond lifecycle, client
reads budgets.

## 8. Exact next action

1. Apply M10 migration to the dev DB and smoke-test:
   `docker compose up -d postgres`, `alembic upgrade head` (backend container
   runs migrations on start), create a project via UI and walk the lifecycle.
2. Commit the M10 work when the owner asks.
3. Then **M3 — Computed project health** (schedule + budget + safety signals,
   audited admin override) over ACTIVE projects only.

## 9. Ambiguities / conflicts captured from the M10+M11 requirements

- ~~Who transitions lifecycle vs the old `PATCH /projects` supervisor path~~ —
  **RESOLVED (M10):** transitions are admin-only dedicated endpoints; PATCH no
  longer accepts `status`.
- ~~Seed data: mark demo rows vs env-flag only~~ — **RESOLVED (M10):** env-flag
  only (`ICE_SEED_DEMO`), no schema marker.
- ~~Status model: extend enum vs replace~~ — **RESOLVED (M10):** extended
  (`draft`/`archived` appended; existing values intact).
- `Project.budget_spent` remains derived (`== SUM(job_costs)`, M4 invariant);
  lifecycle/archive must not bypass it — verified by test across archive/restore.
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
- M10 migration not yet applied to the dev DB (revision written but `alembic
  upgrade head` not run this session).
- M11 owner decisions still required (see §8/§9 in previous notes).
- Deviating from roadmap UI guidance (replacing `alert()` with inline errors)
  applies to new components only; existing panels still use `alert()`.