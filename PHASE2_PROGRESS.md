# Phase 2 Progress — Timeline, Daily Site Logs, Inventory, Finance Scaffold

**Date**: August 9, 2026
**Branch**: `claude-development`
**Scope agreed**: Gantt/timeline, daily site logs, basic inventory & procurement, financial/accounting integration (scaffold only — see blockers below).

---

## What's built and verified

### 1. Gantt/timeline (`Task` model)
- One flat, ordered list of tasks per project — name, date range, status (`not_started`/`in_progress`/`completed`/`blocked`), percent complete, optional predecessor.
- API: `GET/POST /projects/{id}/tasks`, `PATCH/DELETE /projects/{id}/tasks/{task_id}`.
- RBAC: admin writes anywhere; site supervisor writes only on projects they're assigned to; everyone with project access can read.
- Frontend: `ProjectTimeline.tsx` — proportional bar per task scaled to the project's own start/target-end date span, inline status dropdown + percent-complete slider, delete on hover.

### 2. Daily site logs (`DailySiteLog` model)
- Append-only field report per project: date, work summary, issues, workers present, weather, photo URLs (empty until GCS upload lands).
- API: `GET/POST /projects/{id}/site-logs`. No update/delete — same "write-once" philosophy as `AuditLog`.
- RBAC: same write rule as tasks (admin / assigned supervisor); read follows project access.
- Frontend: `DailySiteLogs.tsx` — feed + create form.

### 3. Basic inventory & procurement (`InventoryItem`, `StockMovement`)
- `quantity_on_hand` is a denormalized running total; every change goes through an immutable `StockMovement` ledger row, so the ledger is always the source of truth if the total ever needs reconciling.
- Movement sign convention: `received`/`adjusted` add, `consumed`/`transferred` subtract. A movement that would take stock below zero is rejected (400).
- API: `GET/POST /projects/{id}/inventory`, `PATCH /projects/{id}/inventory/{item_id}`, `GET/POST /projects/{id}/inventory/{item_id}/movements`.
- RBAC: admin + procurement manager write; read follows project access.
- Frontend: `InventoryPanel.tsx` — item list with low-stock flag (`quantity_on_hand <= reorder_threshold`), add-item form, per-item movement form.
- QR-code scanning (mentioned in the original scope as a stretch goal) isn't built — but the schema needs no change for it later: a scan would just create a `StockMovement` row the same way the manual form does.

### 4. Financial & accounting integration — **scaffold only, not functional**
- `JobCost` (costed line items per project) and `Invoice` (milestone invoices) tables exist and migrate cleanly.
- `Invoice.external_ref` / `external_sync_status` columns are placeholders for a future QuickBooks/Xero connector — currently unused.
- **No API endpoints, no frontend, no sync logic was built for this pillar.** See "What's blocking financial sync" below — this needed a decision from you before writing throwaway code.

### Cross-cutting
- All new writes go through `record_audit()` — task/log/inventory changes show up in `GET /api/v1/audit/logs` alongside Phase 1's user/project audit trail.
- Shared project-access logic (`_get_project_or_404` / `_assert_can_view`) was pulled out of `api/v1/projects.py` into `app/api/project_access.py` so the three new endpoint modules don't each reimplement it — `projects.py` itself now imports from there too.

---

## Bugs found and fixed in the *existing* Phase 1 "critical fixes" work

Verifying this properly (see "How this was tested" below) surfaced three real defects in the test framework added earlier this session, before any Phase 2 code existed. Flagging these explicitly since they were presented as done and verified:

1. **The test suite could never have run.** It was configured to use an in-memory SQLite database, but the schema uses Postgres-native `UUID`/`ENUM`/`JSONB` types SQLite can't emulate — and `aiosqlite` was never even added to dependencies. Fixed by pointing tests at a real, throwaway Postgres database (`ice_test_db`, auto-created, dropped clean each test) instead.
2. **`requirements.txt` had a version conflict.** `pytest`/`httpx` were pinned there at different versions than the pre-existing pins in `requirements-dev.txt`, so `pip install` on both files together failed outright. Test tooling doesn't belong in the runtime requirements file anyway — removed from `requirements.txt`.
3. **`greenlet` was never declared**, even though SQLAlchemy's async engine requires it. It happened to be present transitively in the Docker (Linux) image but wasn't guaranteed — now pinned explicitly (`greenlet==3.1.1`).

All three are fixed as part of this Phase 2 commit. The full suite (33 tests: 9 auth, 8 users, 7 tasks, 4 site-logs, 5 inventory) passes against real Postgres.

---

## How this was tested (not just claimed)

Nothing below is asserted without having actually run it:

- **Backend**: built a local virtualenv, installed `requirements.txt` + `requirements-dev.txt`, ran `pytest tests/ -v` against the docker-compose Postgres container — 33/33 passed.
- **Migration**: rebuilt the backend Docker image (new deps + migration file aren't in the bind-mounted `app/` path) and let the container's own `alembic upgrade head` apply `8f3a1c2d9e01` — confirmed via `alembic current` and the startup log.
- **Live API smoke test**: logged in as the seeded admin, created a task/site-log/inventory item via `curl` against the running container, and read back `GET /api/v1/audit/logs` to confirm each write was audited.
- **Frontend**: `tsc -b` (type-check), `oxlint` (no new warnings), `vite build` (production build) all clean.
- **Full browser E2E**: started the Vite dev server, drove headless Chromium (Playwright) through the actual login form → Command Center → Project Detail, then filled and submitted the real "Add task" / "New entry" / "Add item" forms in the UI (not the API directly) and confirmed each new record rendered — with zero browser console or network errors. Screenshots were inspected, not just captured.

---

## What's blocking financial/accounting sync

QuickBooks and Xero sync needs, before any connector code is worth writing:

1. **A registered OAuth app** with each provider (QuickBooks Developer account + app; Xero Developer account + app) — gives you a `client_id`/`client_secret`.
2. **A sandbox company/organization** on each platform to test against without touching real books.
3. **A decision on sync direction and cadence** — e.g., invoices created in ICE push to QuickBooks/Xero on create, or a scheduled reconciliation job; whether payment status syncs back into ICE.
4. **Where secrets live** — these can't go in `.env` committed to git; needs a secrets manager decision (GCP Secret Manager, matching the `GCP_PROJECT_ID` already in config) before the connector is wired up.

Once you have (1)–(2), the shortest path is: `JobCost`/`Invoice` CRUD endpoints (straightforward, same pattern as everything else here) + a background job (Celery, already planned for Phase 2 per the original roadmap) that pushes/pulls against whichever provider's API using the OAuth credentials. Estimate once credentials exist: 3-5 days for one provider's basic invoice sync.

---

## Files added

```
backend/app/models/task.py
backend/app/models/site_log.py
backend/app/models/inventory.py
backend/app/models/finance.py
backend/app/schemas/task.py
backend/app/schemas/site_log.py
backend/app/schemas/inventory.py
backend/app/api/project_access.py
backend/app/api/v1/tasks.py
backend/app/api/v1/site_logs.py
backend/app/api/v1/inventory.py
backend/alembic/versions/8f3a1c2d9e01_phase2_tasks_site_logs_inventory_.py
backend/tests/test_tasks.py
backend/tests/test_site_logs.py
backend/tests/test_inventory.py
frontend/src/components/ProjectTimeline.tsx
frontend/src/components/DailySiteLogs.tsx
frontend/src/components/InventoryPanel.tsx
```

## Files modified

```
backend/app/models/__init__.py          — register new models
backend/app/api/v1/router.py            — mount tasks/site-logs/inventory/audit routers
backend/app/api/v1/projects.py          — use shared project_access helpers instead of private copies
backend/requirements.txt                — add greenlet (was missing), remove misplaced test deps
backend/requirements-dev.txt            — add pytest-cov
backend/tests/conftest.py               — real-Postgres fixtures, httpx.AsyncClient, rate-limit-safe client
backend/tests/test_auth.py              — httpx.AsyncClient conversion, add rate-limit test, fix wrong 403 assertion
backend/tests/test_users.py             — httpx.AsyncClient conversion, use shared auth_header helper
backend/pytest.ini                      — pin asyncio fixture loop scope
frontend/src/types/index.ts             — Task/DailySiteLog/InventoryItem/StockMovement types
frontend/src/pages/ProjectDetail.tsx    — replace "arrives in Phase 2" placeholder with the three new panels
```

---

## Not done (explicitly out of scope this round)

- Financial/accounting sync itself (see blockers above) — schema only.
- QR-code scanning for inventory (stretch goal, schema supports it later without migration).
- Cross-project inventory rollup view (sidebar "Inventory" nav item is still marked Phase 2 — what's built is per-project, accessible from each Project Detail page).
- Photo upload for daily site logs (`photo_urls` column exists, empty until GCS integration).
- Celery/background jobs (still Phase 2 roadmap, not started).

---

## Next steps

1. Decide on QuickBooks vs. Xero (or both) and register the OAuth app(s) — that unblocks financial sync.
2. Confirm whether a cross-project inventory rollup (procurement manager's "see stock across all 15 sites" view) is wanted, or per-project is sufficient for now.
3. Continue with Celery background jobs for the health-indicator computation mentioned in the original Phase 1 model comments.
