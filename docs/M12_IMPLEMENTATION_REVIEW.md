# M12 — Dynamic Gantt & Dependency Scheduling — Implementation Review

**Status:** IMPLEMENTED, fully verified (not yet committed).
**Date:** Aug 13, 2026.
**Plan:** `docs/M12_IMPLEMENTATION_PLAN.md` (canonical, unchanged). This
document records what was actually implemented and verified.

## 1. Implementation summary

M12 turns the M7-validated task dependencies into actual scheduling: a pure,
deterministic, **push-only Finish-to-Start** pass (`successor.start >=
predecessor.end + 1 calendar day`) auto-shifts dependent tasks when an
upstream task's dates change, transitively and idempotently, inside the
existing project row lock. The timeline UI gained a dependency picker,
per-task date editing, a predecessor tag, and a "N tasks shifted" notice.
Clients remain read-only. No migration, no new endpoints, no new dependencies,
no Phase 4 infrastructure.

## 2. Files changed

- `backend/app/services/tasks.py` — `ScheduleShift` + `apply_schedule()`.
- `backend/app/api/v1/tasks.py` — schedule pass on create/PATCH/delete +
  `_audit_schedule_shifts` (`task_schedule_shift` rows).
- `backend/tests/test_task_scheduling.py` — new (21 tests).
- `frontend/src/components/ProjectTimeline.tsx` — dependency picker, date
  editing, predecessor tag, shift notice.
- `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md`,
  `docs/M12_IMPLEMENTATION_REVIEW.md`.

## 3. Migration revision

**None.** Alembic head unchanged (`i7d8e9f0a1b2`); the schema already had
`depends_on_id` (FK `tasks.id` ON DELETE SET NULL), `start_date`/`end_date`,
and `sort_order`.

## 4. API behavior

- `POST /projects/{id}/tasks` — unchanged request; a new task's dates are
  auto-adjusted if they violate F-S vs its chosen predecessor (create-time
  scheduling; D15).
- `PATCH /projects/{id}/tasks/{tid}` — unchanged request (already accepts
  `depends_on_id`, `start_date`, `end_date`); now also cascades to dependents.
- `DELETE /projects/{id}/tasks/{tid}` — unchanged; dependents keep dates (FK
  SET NULL clears edges).
- `GET /projects/{id}/tasks` — unchanged; frontend refetches after mutations.
- No new endpoints. Response compatibility preserved.

## 5. Scheduling semantics (as implemented)

- Push-only, forward-only: tasks are never pulled backward.
- F-S: `successor.start >= predecessor.end + 1 calendar day`.
- Minimum required shift; duration preserved (`end` moves with `start`).
- Transitive cascade to a forward-only fixpoint (bounded passes; a cycle that
  somehow slipped through raises instead of looping).
- Idempotent: an already-consistent schedule produces zero shifts; re-running
  changes nothing (no cumulative double-shift).
- Deterministic: the least fixpoint is unique; processing uses a stable order.
- Single predecessor per task; fan-out (one predecessor, many successors)
  supported; diamonds not applicable under the single-predecessor model.

## 6. Concurrency behavior

- All scheduling runs inside the existing **project row lock**
  (`get_project_for_update` in `_assert_can_write`); the user change, all
  dependent shifts, and all audits commit atomically in one transaction.
- All project tasks are loaded in one query; no nested queries, no N+1.
- Two real two-session concurrency tests verify deterministic final schedules
  with no lost updates (moving A's end vs moving B's start; and an upstream
  move racing a dependent push — final B.start = max(user value, A.end+1)).

## 7. RBAC / security review

- Admin + assigned supervisor write (unchanged `write_roles` +
  `_assert_can_write`); procurement unchanged; **client read-only** — GET 200,
  PATCH (dates and dependency) → 403, verified in tests and live smoke.
- Project assignment isolation, archived-404, and M7 validation (date order,
  self-dependency, same-project, cycle) preserved and regression-tested.
- Google-authenticated users take the identical RBAC path (M11 unchanged).
- No IDOR: dependencies are validated same-project; scheduling is
  project-scoped and runs inside the authorized write path.

## 8. Audit behavior

- Existing `create`/`update`/`delete` rows for the user-requested change.
- Each automatically shifted dependent gets a **`task_schedule_shift`** row in
  the same transaction: `record_id` = shifted task, `changes` =
  `start_date`/`end_date` old/new + `caused_by_task_id` (immediate
  predecessor). No shift → no `task_schedule_shift` row (tested). No secrets or
  sensitive data logged.

## 9. Frontend behavior

- `ProjectTimeline` extended only: dependency picker (create + per-task),
  start/end date inputs, predecessor tag, transient "N tasks shifted" notice.
- Gated by existing `canWrite`; clients see the read-only bars/tags only.
- No new library, no unrelated UI refactor; existing styling preserved.

## 10. Test results

- `pytest -q tests/test_task_scheduling.py`: **21 passed**.
- Full backend suite `pytest -q`: **244 passed** (was 223; incl. migration
  chain and all M7/M9/M10/M11/M6 tests).
- Frontend `npm run build`: passed. `npm run lint`: 1 baseline warning only.
- Ruff: 2 baseline findings unchanged. Mypy: 10 baseline findings unchanged.
  CI baseline-delta gates: PASS (ruff/mypy/oxlint).
- `git diff --check`: clean.

## 11. Migration verification

N/A — no migration created or applied. Alembic head remains `i7d8e9f0a1b2`;
the migration-chain test passes within the full suite.

## 12. Render smoke-test results (live dev stack)

Ran against a scratch Postgres DB (`alembic upgrade head` + seeded demo users)
served by a live `uvicorn` backend and the Vite dev server (HTTP smoke; no
browser automation):

1. Admin created Task A (Foundation) and Task B (Framing); **B depends on A**. ✓
2. Moved A's end 08-05 → 08-15: **B auto-shifted to 08-16..08-18**. ✓
3. Added Task C depending on B: **transitive cascade** (C = 08-19..08-20). ✓
4. Moved A backward to 08-05: **B and C were NOT pulled backward** (push-only). ✓
5. Re-GET (refresh): **dates persisted**. ✓
6. Client login: timeline **read-only** (GET 200 with cascade results); direct
   PATCH of dates **403**; direct dependency PATCH **403**. ✓
7. Frontend dev server served 200. ✓

Not performed (not claimed): browser click-through; a real Google-authenticated
client smoke.

## 13. Security review

- Scheduling cannot bypass task authorization (runs inside the authorized,
  locked write path); dependency changes require the same authorization as task
  updates.
- M6 client boundary, M9/M11 session/auth, and M10 archive semantics intact
  (full-suite + client-portal tests green).
- No new attack surface; no secrets.

## 14. Documentation updates

- `docs/CURRENT_STATE.md` (M12 §4b bullet, Dynamic-Gantt limitation updated,
  test count 244), `docs/ROADMAP.md` (M12 DONE), `docs/SESSION_NOTES.md` (§16).
- `docs/M12_IMPLEMENTATION_PLAN.md` — **unchanged** (canonical plan).

## 15. Remaining concerns

- Vendor/schedule-change **notifications** remain a separate gap (PRD 4.1.2
  second half; may need email infrastructure).
- Non-working-day calendars, multi-predecessor support, critical-path analysis,
  resource leveling: explicitly out of scope.
- Browser click-through and Google-client smoke not performed (environment
  constraints); automated tests + live HTTP smoke cover the behavior.

## 16. Final verdict

**SAFE TO COMMIT.** M12 is implemented per the owner-approved plan, with no
migration, no new dependencies, no Phase 4 dependency, full automated
verification (244 tests, frontend build/lint, baseline-delta gates) and a live
dev-stack smoke. Nothing was committed or pushed.
