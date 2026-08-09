# Session Notes — Phase 3 kickoff (M1 + M2)

**Session date:** Aug 9–10, 2026. Branch `claude-development`.

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

## 2. Files created / modified (all UNCOMMITTED)

Created:
- `backend/app/services/` + `app/services/inventory.py` (thin services layer starts here)
- `backend/alembic/versions/a4b6c8d9e2f3_m1_stock_movements_index.py`
- `backend/alembic/versions/b5c7d9e1f203_m2_unique_project_assignments.py`
- `backend/tests/test_projects.py`
- `frontend/src/components/ProjectAssignments.tsx`
- `docs/SESSION_NOTES.md` (this file)

Modified: `backend/app/api/v1/inventory.py`, `backend/app/api/v1/projects.py`,
`backend/app/models/project.py`, `backend/app/schemas/inventory.py`,
`backend/app/schemas/project.py`, `backend/tests/test_inventory.py`,
`frontend/src/pages/ProjectDetail.tsx`, `frontend/src/types/index.ts`,
`docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`.

## 3. Important decisions

- M1 first (correctness bug, independent, low blast radius), then M2
  (unlocks real RBAC and M3/M6 scoping).
- Reconciliation is a **report-only** endpoint (admins fix drift via an ADJUSTED
  movement), not an auto-correcting job.
- Thin `services/` layer introduced early (route now stays lean); further Phase 3
  domain logic (finance, health) expected to follow the same pattern.
- Assignment endpoints are admin-only and restrict assignable roles to
  supervisor/client (admin/proc see all projects by role).
- DB migration applied to dev DB is now at rev `b5c7d9e1f203` (head).

## 4. Current project state

Phases 1 & 2 complete and intact. 45/45 backend tests pass against real Postgres.
Migrations `a4b6c8d9e2f3` and `b5c7d9e1f203` applied to the dev DB.

## 5. Current Phase

Phase 3 — "Integrity, Operable RBAC & the Finance Pillar".

## 6. Current milestone

M2 (project-assignment management) — **done**, awaiting commit.

## 7. Not yet implemented (Phase 3 remaining)

- **M4** Job costing (`JobCost` CRUD + `cost_code` enum; `budget_spent` derived).
- **M5** Invoicing (milestone → invoice generation).
- **M3** Computed project health (+ audited manual override) — budget part needs M4.
- **M6** Client view-only scope (no budget fields for client role).
- **M7** Task date-order validation on update + dependency cycle detection.
- **M8** Idempotency keys on movement/site-log/invoice POSTs.
- **M9** Token security: refresh rotation + server-side revocation.
- Phase 3 DB stubs still pending: unique `inventory_items (project_id, name)`,
  `daily_site_logs (project_id, log_date)`; `cost_code`; finance indexes.
- Pre-existing debt (not in Phase 3 scope to fix unilaterally): ruff 4 F401 errors,
  mypy 10 errors, no `test_projects.py` CRUD coverage, client reads budgets.

## 8. Exact next action

1. Commit today's M1+M2 work (stage the 10 modified + 5 new files listed in §2;
   nothing after `d0a9e5c` is committed).
2. Start **M4 — Job Costing** (M4 precedes M3's budget-health): add `cost_code`
   enum to `job_costs`, migration, `GET/POST /projects/{id}/job-costs`, derive
   `budget_spent`, tests, update `CURRENT_STATE.md`.

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