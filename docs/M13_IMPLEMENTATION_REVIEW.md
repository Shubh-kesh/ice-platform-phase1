# M13 — Notifications & Alerts — Implementation Review

**Status:** IMPLEMENTED, fully verified (not yet committed).
**Date:** Aug 13, 2026.
**Plan:** `docs/M13_IMPLEMENTATION_PLAN.md` (canonical, unchanged). This
document records what was actually implemented and verified.

## 1. Implementation summary

In-app, event-driven notifications: a `notifications` table + centralized
service + user-scoped API + four event hooks + an AppShell bell. Notifications
are created atomically with their triggering business event, never expose
another user's data, and do not duplicate under idempotent retries or repeated
operations. No Phase 4 infrastructure, no workers, no email.

## 2. Exact files changed

- `backend/alembic/versions/j8e9f0a1b2c3_m13_notifications.py` (new)
- `backend/app/models/notification.py` (new) + `models/__init__.py`
- `backend/app/schemas/notification.py` (new)
- `backend/app/services/notifications.py` (new)
- `backend/app/api/v1/notifications.py` (new) + `api/v1/router.py`
- Hooks: `api/v1/tasks.py`, `api/v1/invoicing.py`, `api/v1/inventory.py`,
  `api/v1/projects.py`
- `backend/tests/test_notifications.py` (new), `tests/test_migrations.py`
  (HEAD_REVISION + notifications table checks)
- `frontend/src/components/NotificationsBell.tsx` (new), `AppShell.tsx`,
  `lib/api.ts`, `types/index.ts`
- `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md`,
  `docs/M13_IMPLEMENTATION_REVIEW.md`

## 3. Migration revision and status

- Revision `j8e9f0a1b2c3` (down `i7d8e9f0a1b2`); additive `notifications` table
  (user_id FK CASCADE, project_id FK CASCADE nullable, type/title/body/link,
  read_at, created_at; indexes `(user_id, read_at)`, `(user_id, created_at)`).
- `type` is a constrained String (app-level enum) — deliberately avoids the
  repo's documented native-enum alembic pitfall (SESSION_NOTES); the DB value
  is the same string label.
- Upgrade from head, clean downgrade (drops the table), and replay all verified
  by the migration-chain test.

## 4. Notification types implemented

`task_schedule_shift`, `milestone_invoice_issued`, `inventory_low_stock`,
`project_assigned`.

## 5. Recipient rules

- Schedule shift → project-assigned **site supervisors** + **admins**.
- Invoice issued (payment request) → project-assigned **client** + **admins**.
- Low-stock crossing → **all active procurement managers** + **admins**
  (deviation: procurement is not project-assignable and has global project
  visibility — project-assigned procurement cannot exist).
- Assignment → the assigned supervisor/client.

## 6. Event hook integration

- `tasks.py`: after the M12 schedule pass produces ≥1 shift → notify.
- `invoicing.py` `issue_invoice`: DRAFT→SENT → notify client + admins.
- `inventory.py`: `create_inventory_item` (initial at/below threshold) and
  `record_movement` (old > threshold and new <= threshold crossing) → notify.
- `projects.py` `assign_user_to_project` → notify the assigned user.

## 7. Transaction/atomicity behavior

All notification inserts happen in the **same transaction** as the event
(service never commits). A rolled-back event (e.g., a below-zero movement 400)
creates no notification — verified by test. No post-commit creation, so
notifications cannot be silently lost.

## 8. Deduplication/concurrency behavior

- Low-stock: only on the crossing (old > threshold and new <= threshold);
  further below-threshold movements create nothing (verified).
- M8 idempotent replay short-circuits before the handler body → no duplicate
  notifications (verified with an `Idempotency-Key` retry).
- Schedule: a repeat PATCH that produces no shift creates no notification.
- Concurrency: real two-session test — serialized project writes, ≥1
  notification delivered, F-S holds, no lost notifications.

## 9. API behavior

`GET /notifications` (caller's, newest first, optional `unread_only`),
`GET /notifications/unread-count`, `POST /notifications/read-all` (204),
`POST /notifications/{id}/read` (owner-only; another user's id → 404).
Ownership derives from the auth dependency; no client-supplied user id is
trusted. No public creation endpoint.

## 10. RBAC/security review

- Notifications are user-scoped; IDOR on another user's notification → 404
  (verified).
- Recipients reuse the existing role/assignment model; procurement/admins have
  global visibility so no cross-project data leak.
- Content is minimal (title/body/link; no amounts, no secrets, no tokens).
- Clients receive only their own feed; M6 project isolation untouched (client
  can't reach another project's invoice/schedule data via notifications —
  content has no such data; project isolation tests remain green).
- M9/M11 authentication integration unchanged (any authenticated user has a
  feed; Google users follow the same path).

## 11. Frontend changes

`NotificationsBell` in the AppShell header: unread-count badge (30s poll),
dropdown feed with title/body/time/read state, mark-read on open (navigates to
the project link), mark-all-read, empty/loading states. Uses existing TanStack
Query + design system; no new library. Gated by authenticated layout only
(inside AppShell); no project data exposed beyond the user's own feed.

## 12. Test results

- `tests/test_notifications.py`: **12 passed**.
- Full backend suite: **256 passed** (was 244; incl. migration chain).
- Migration chain: green through `j8e9f0a1b2c3` (upgrade/downgrade/replay).

## 13. Frontend results

- `npm run build`: passed. `npm run lint`: 1 baseline warning only.

## 14. Quality-gate results

- Ruff: 2 baseline findings unchanged. Mypy: 10 baseline findings unchanged.
  Oxlint: 1 baseline warning unchanged. CI baseline-delta gates all **PASS**.
- `git diff --check`: clean.

## 15. Docker/Render smoke-test results (live dev stack)

Ran against a scratch Postgres (alembic upgrade through `j8e9f0a1b2c3` + seeded
demo users), live uvicorn + Vite (HTTP smoke; no browser automation):

1. Schedule change (M12) → supervisor + admin `task_schedule_shift` ✓
2. Invoice issue (M5) → client `milestone_invoice_issued` ✓
3. Low-stock crossing (inventory) → procurement `inventory_low_stock`,
   deduped on a further below-threshold movement ✓
4. Assignment (M2) → assigned user `project_assigned` ✓
5. Unread count, mark-read (idempotent), mark-all-read ✓
6. Cross-user: admin reading the supervisor's notification → 404 ✓
7. Refresh → feed persisted ✓
8. Frontend dev server served 200 ✓

Not performed/not claimed: browser click-through, email/push (out of scope),
real Google-authenticated client smoke.

## 16. Deviations from plan

- **Low-stock recipients:** plan said "project-assigned procurement";
  implemented as **global active procurement + admins** because procurement is
  not project-assignable (`_ASSIGNABLE_ROLES = supervisor, client`) and has
  global project visibility. This is required for the feature to work at all
  and is RBAC-safe.
- **Notification `type`:** stored as a constrained String (app-level enum)
  rather than a native DB enum, to avoid the documented alembic native-enum
  pitfall; values are identical string labels.

## 17. Known limitations

- In-app only — no email/SMS/push (external provider + secrets deferred).
- 7-day low-stock demand forecast is Phase 5 (static reorder threshold used).
- No notification preferences/retention/cleanup (small rows; deferred).

## 18. Final verdict

**SAFE TO COMMIT.** M13 is implemented per the plan (with one documented
recipient-rule correction), verified end-to-end: 256 backend tests, migration
chain through `j8e9f0a1b2c3`, frontend build/lint clean, baselines unchanged,
live dev-stack smoke green, and a dedicated security review (ownership/IDOR,
isolation, atomicity, dedupe, concurrency) found no issues. Nothing committed
or pushed.
