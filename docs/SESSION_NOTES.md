# Session Notes — Phase 3 kickoff (M1 + M2)

**Session dates:** Aug 9–10, 2026. Branch `claude-development`.

See `CLAUDE.md`, `docs/ROADMAP.md` for durable context. This file records only
session-local details needed to resume.

## 1. What we accomplished

- Committed `d0a9e5c` (docs foundation + roadmap). Nothing after that is committed.
- Planned Phase 3 (7 milestones + analysis) and got approval.
- **M1 — inventory integrity:** row-locked `record_movement()` (`SELECT ... FOR UPDATE`),
  ledger-reconciliation service + `GET /projects/{id}/inventory/reconciliation`.
- **M2 — project-assignment management:** unique constraint on
  `(project_id, user_id)` + admin-only assign/unassign API + admin UI panel.
- Tests grew 33 → 45 (all passing); frontend `tsc + vite build` clean.
- **M4 — job costing (this session):** `CostCode` enum on `job_costs` (replaces the
  unused free-text `category` column), job-cost CRUD (`GET/POST/PATCH/DELETE
  /projects/{id}/job-costs`), derived `Project.budget_spent` (= `SUM(job_costs)`,
  recomputed in-transaction on every mutation), admin/proc-only
  `GET /projects/{id}/budget` roll-up, budget roll-up schema + finance service
  (`app/services/finance.py`), migration `c6d8e0f2a415`, 9 new tests,
  `JobCostsPanel` frontend. Suite grew 45 → **54 passing**; ruff/mypy/tsc clean
  (no new findings).

## 2. Files created / modified (all UNCOMMITTED)

Created:
- `backend/app/services/` + `app/services/inventory.py` (thin services layer starts here)
- `backend/alembic/versions/a4b6c8d9e2f3_m1_stock_movements_index.py`
- `backend/alembic/versions/b5c7d9e1f203_m2_unique_project_assignments.py`
- `backend/tests/test_projects.py`
- `frontend/src/components/ProjectAssignments.tsx`
- `docs/SESSION_NOTES.md` (this file)
- `backend/app/services/finance.py` (M4 — budget roll-up domain math)
- `backend/app/schemas/finance.py` (M4 — job-cost + budget rollup contracts)
- `backend/app/api/v1/finance.py` (M4 — job-cost CRUD + budget roll-up routes)
- `backend/alembic/versions/c6d8e0f2a415_m4_job_costs_cost_code.py` (M4)
- `backend/tests/test_finance.py` (M4 — 9 tests)
- `frontend/src/components/JobCostsPanel.tsx` (M4)

Modified: `backend/app/api/v1/inventory.py`, `backend/app/api/v1/projects.py`,
`backend/app/models/project.py`, `backend/app/schemas/inventory.py`,
`backend/app/schemas/project.py`, `backend/tests/test_inventory.py`,
`frontend/src/pages/ProjectDetail.tsx`, `frontend/src/types/index.ts`,
`docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`.
Modified (M4): `backend/app/models/finance.py` (CostCode enum, drop `category`),
`backend/app/models/__init__.py`, `backend/app/api/v1/router.py`,
`frontend/src/pages/ProjectDetail.tsx`, `frontend/src/types/index.ts`,
`docs/CURRENT_STATE.md`.

## 3. Important decisions

- M1 first (correctness bug, independent, low blast radius), then M2
  (unlocks real RBAC and M3/M6 scoping).
- Reconciliation is a **report-only** endpoint (admins fix drift via an ADJUSTED
  movement), not an auto-correcting job.
- Thin `services/` layer introduced early (route now stays lean); further Phase 3
  domain logic (finance, health) expected to follow the same pattern.
- Assignment endpoints are admin-only and restrict assignable roles to
  supervisor/client (admin/proc see all projects by role).
- DB migration applied to dev DB is now at rev `c6d8e0f2a415` (head).

## 4. Current project state

Phases 1 & 2 complete and intact; Phase 3 M1/M2/M4 in the working tree (uncommitted).
54/54 backend tests pass against real Postgres.
Migrations `a4b6c8d9e2f3`, `b5c7d9e1f203`, `c6d8e0f2a415` applied to the dev DB.

## 5. Current Phase

Phase 3 — "Integrity, Operable RBAC & the Finance Pillar".

## 6. Current milestone

M4 (job costing) — **done**, awaiting commit. (M1+M2 from the prior session also uncommitted.)

## 7. Not yet implemented (Phase 3 remaining)

- **M5** Invoicing (milestone → invoice generation).
- **M3** Computed project health (+ audited manual override) — **budget part now unblocked by M4** (budget_spent is derived; health can compute from real spend vs total).
- **M6** Client view-only scope (no budget fields for client role).
- **M7** Task date-order validation on update + dependency cycle detection.
- **M8** Idempotency keys on movement/site-log/invoice POSTs.
- **M9** Token security: refresh rotation + server-side revocation.
- Phase 3 DB stubs still pending: unique `inventory_items (project_id, name)`,
  `daily_site_logs (project_id, log_date)`; finance indexes (done for job_costs);
  stock_movements/audit_logs list indexes.
- Pre-existing debt (not in Phase 3 scope to fix unilaterally): ruff 4 F401 errors,
  mypy 10 errors, no `test_projects.py` CRUD coverage, client reads budgets.

## 8. Exact next action

1. Commit the uncommitted work (M1+M2 from last session **and** M4 from today) —
   stage the files listed in §2; nothing after `d0a9e5c` is committed.
2. Start **M5 — Invoicing**: invoice CRUD + milestone→invoice generation rules
   (e.g. "Slab Completed → 20%"), reusing `models/finance.py` `Invoice` schema +
   `finance.py` router; then M3 (computed health) can use derived budget.
   Update `CURRENT_STATE.md` after completion.

## 9. Unresolved questions / issues

- Postgres container **auto-stops** between sessions; restart with
  `docker compose up -d postgres` before running tests.
- Test env: pinned `requirements-dev.txt` was installed into the `py310_env`
  conda env so `pytest`/`ruff`/`mypy` run there
  (`/opt/miniconda3/envs/py310_env/bin/python -m pytest tests/ -q`).
- TBD from user: ordering/split of M4 vs M5 vs M3, and whether M9 (token
  hardening) should land before finance work.
- Deviating from roadmap UI guidance (replacing `alert()` with inline errors)
  applies to new components only; existing panels still use `alert()`.