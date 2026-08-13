# M13 — Notifications & Alerts: Implementation Plan

**Status:** PLANNED (not implemented). No code, migrations, or commits created.
**Date:** Aug 13, 2026.
**Branches/commits this plan assumes:** M1–M12 + M6 close-out + P4.1 shipped;
Alembic head `i7d8e9f0a1b2`. Phase 4 production infrastructure (P4.2–P4.6) is
intentionally **deferred** — M13 must not depend on it.
**Source of truth:** `docs/ROADMAP.md`, `docs/CURRENT_STATE.md`,
`docs/ARCHITECTURE.md`, `docs/PRODUCT_REQUIREMENTS.md` (PRD §4.1.2, §4.2.2,
§4.3.2), and the code. This is the plan; the post-implementation record belongs
in `docs/M13_IMPLEMENTATION_REVIEW.md`.

---

## 1. Objective

Deliver **in-app, event-driven notifications and alerts** so that schedule
changes, client payment requests, and low-stock conditions surface to the right
people without manual polling. This is the second half of PRD §4.1.2 ("changing
task dates … triggers vendor notifications") that M12 intentionally left as a
separate gap, plus the milestone-invoice (client) and low-stock (procurement)
alerts. No Phase 4 infrastructure, no workers, no email (email is a deferred
owner-decision tier).

## 2. Current implementation state (verified)

- **Events exist to notify on** (created inside locked transactions, all
  audited): M12 `apply_schedule` produces `ScheduleShift` records per shifted
  dependent on task create/PATCH/delete; M5 `issue` moves an invoice
  DRAFT→SENT (the client "payment request"); inventory `record_movement`
  updates `quantity_on_hand`; M2 `assign_user_to_project` grants project
  access.
- **Recipients are resolvable** via existing RBAC: `project_assignments`
  (assigned supervisors/clients), roles (`UserRole`), and
  `assert_can_view_project` / `assert_can_read_users`-style helpers.
- **No notifications exist:** no table, no endpoint, no UI, no notification
  creation anywhere (verified — zero matches for `notification` in
  `backend/app/api` and `backend/app/services`).
- **Audit** (`record_audit`) is separate from any user-facing notification; M13
  must not turn notifications into a second audit system.
- **Frontend:** `AppShell` header exists (date strip + env badge) with room for
  a bell; TanStack Query pattern established.

## 3. Requirements

- PRD §4.1.2: schedule changes notify relevant recipients.
- PRD §4.2.2: automated alerts when a material falls below threshold for
  scheduled work — v1 uses the **static reorder threshold** (7-day demand
  forecast is Phase 5 and needs a worker); alert goes to procurement.
- PRD §4.3.2: milestone completion generates a client payment request — v1
  also notifies the client when an invoice is issued.
- Notifications are **in-app**; recipients are the assigned users/roles the
  event concerns; each notification links to the project; unread count + mark
  read.

## 4. User / RBAC behavior

- **Notification ownership:** every notification belongs to exactly one user;
  an endpoint only ever returns the caller's own notifications (403/404 for
  anyone else's — IDOR-guarded).
- **Recipient scoping per event:**
  - `task_schedule_shift` (project schedule changed) → project-assigned
    **site supervisors** (the operational team) + **admins**.
  - `milestone_invoice_issued` (payment request) → the project-assigned
    **client** + **admins**.
  - `inventory_low_stock` → project-assigned **procurement managers** +
    **admins**.
  - `project_assigned` → the newly assigned supervisor/client.
- Clients remain **read-only** on project surfaces (M6 intact); notifications
  are the client's own user-scoped feed (read + mark-read only).
- Google-authenticated users (M11) get the identical path (role/session based).

## 5. Backend / API changes

- **New model `Notification`** (`app/models/notification.py`): `id` (uuid),
  `user_id` (FK users CASCADE), `project_id` (FK projects CASCADE, nullable),
  `type` (enum `notification_type`: `task_schedule_shift`,
  `milestone_invoice_issued`, `inventory_low_stock`, `project_assigned`),
  `title` (string), `body` (string), `link` (string, e.g. `/projects/{id}`),
  `read_at` (datetime, nullable), `created_at`.
- **New service** `app/services/notifications.py`:
  `create_notifications(db, *, project_id, type_, recipients: list[User],
  title, body, link)` — inserts rows in the caller's transaction (atomic with
  the event). Helper `project_recipients(db, project_id, roles)` resolves
  assigned users by role (+ admins).
- **New router** `app/api/v1/notifications.py`:
  - `GET /notifications` — caller's notifications, newest first; optional
    `unread_only=true`; user-scoped (no other user's rows).
  - `GET /notifications/unread-count` — count of `read_at IS NULL`.
  - `POST /notifications/{id}/read` — mark one read (idempotent; owner-only,
    404 for others'). Optionally `POST /notifications/read-all`.
  - Auth: `get_current_user`; no role gate (any authenticated user has their
    own feed).
- **Hook sites (event-driven, same transaction):**
  - `api/v1/tasks.py` — when `_audit_schedule_shifts` has ≥1 shift, notify
    project supervisors + admins ("Schedule updated — N task(s) shifted").
  - `api/v1/invoicing.py` `issue_invoice` — notify assigned client + admins
    ("Payment request issued: {invoice_number}").
  - `api/v1/inventory.py` `record_movement` / `create_inventory_item` — when
    `quantity_on_hand <= reorder_threshold`, notify procurement + admins
    ("Low stock: {item} — {qty} {unit} remaining"). Debounced? No worker; each
    crossing creates one notification (dedupe by (user,project,type,item) in
    the query is an option — see owner decision).
  - `api/v1/projects.py` `assign_user_to_project` — notify the newly assigned
    user ("You now have access to {project}").
- **No new auth/RBAC surface beyond user-scoped ownership.**

## 6. Frontend changes

- `AppShell` header: add a bell button with an unread-count badge
  (`/notifications/unread-count`, polled via TanStack Query `refetchInterval`
  ~30s).
- Dropdown/panel listing the caller's notifications (`/notifications`):
  title, body, relative time, link → navigate to the project; "Mark read"
  per item (and a "mark all read" action).
- New lightweight `NotificationsPanel`/bell component; reuse existing ink/
  blueprint styling; **no new UI library**.

## 7. Database / migration impact

**One new migration** (this is a real feature table):

- `notifications`: uuid PK; `user_id` uuid NOT NULL FK users ON DELETE
  CASCADE; `project_id` uuid NULL FK projects ON DELETE CASCADE; `type`
  varchar (or enum) NOT NULL; `title`/`body` varchar/text NOT NULL; `link`
  varchar NULL; `read_at` timestamptz NULL; `created_at` timestamptz
  server_default now().
- Indexes: `ix_notifications_user_read (user_id, read_at)` (feed + unread
  count), `ix_notifications_user_created (user_id, created_at)`.

New revision after `i7d8e9f0a1b2`; downgrade drops the table (non-destructive).

## 8. Security considerations

- Notifications are **user-scoped**: owner-only reads; direct `{id}` access to
  another user's notification → 404 (never leak existence).
- Recipient selection uses the same role/assignment data as RBAC — no bypass
  of project isolation (a notification about a project is only created for
  users who can see it).
- **No secrets/PII in notification bodies** (titles/links only; no passwords,
  tokens, or internal financial detail beyond what the recipient role may see).
- No new auth surface; Google-authenticated users follow the same path.

## 9. Audit requirements

- Underlying events remain audited as today (`task_schedule_shift`, `update`,
  `issue`, movement audit, `assign`). Notification creation is a **feature
  row**, not an audit event — do not re-audit notifications through
  `record_audit` (no double bookkeeping).
- Optionally record a `notification` audit line for high-value events
  (invoice issued) — decision; default: no new audit actions.

## 10. Test strategy

- **Service:** `create_notifications` inserts N rows for N recipients;
  recipient resolution (supervisors/clients/procurement/admins); project_id
  linkage.
- **API:** GET own feed (200, newest first), `unread_only`, unread-count,
  mark-read (idempotent), mark-read of another user's notification → 404,
  unauthenticated → 401.
- **Event hooks:**
  - task schedule cascade → supervisor/admin notifications created in the same
    transaction (rollback rolls them back too).
  - invoice issued → client notification; DRAFT issue not notified until SENT.
  - inventory movement crossing reorder threshold → procurement notification;
    no notification when still above threshold.
  - assignment → the assigned user is notified.
- **RBAC/client:** clients get only their own feed; project surfaces unchanged
  (M6 tests stay green); no notification grants project access.
- **Concurrency:** two simultaneous events → both notifications present (no
  lost notification); unread-count correct under concurrent reads (plain SQL
  count, no lock needed).
- **Regression:** full backend suite + migration chain; frontend build/lint;
  CI baseline-delta gates.

## 11. Concurrency requirements

- Notification rows are inserted in the **same transaction** as the event
  (atomic; a rolled-back event creates no notifications).
- Unread count and mark-read are simple single-row/SQL operations; mark-read
  is idempotent (`read_at` set once).
- No worker, no queue, no Redis (Phase 4 deferred). Low-stock checks happen on
  the write path (same as reconciliation-era patterns).

## 12. Regression risks

- Adding a hook inside `record_movement`/`issue`/task routes must not change
  existing status codes/behavior → hooks are additive; full suite pins this.
- Notification creation must not fail the underlying operation → wrap hook in
  a safe pattern but keep it in-transaction (a real failure should fail the
  event, consistent with audit semantics).
- Frontend bell must not break non-authenticated pages → only rendered inside
  `AppShell` (authenticated layout).

## 13. Rollback strategy

- App-only + one additive migration. Revert: remove hook calls, router, model,
  service, frontend bell. Downgrade migration drops the `notifications` table
  (non-destructive; no existing data dependency).
- No change to existing tables/data.

## 14. Acceptance criteria

- A schedule shift creates notifications for the project's supervisors + admins.
- An issued invoice creates a payment-request notification for the assigned
  client.
- Crossing a reorder threshold creates a low-stock notification for
  procurement.
- Each user sees only their own notifications; unread count matches; mark-read
  works and is idempotent.
- M6/M9/M10/M11/M12 behavior unchanged; full suite green; baselines unchanged.
- No worker/email/Phase 4 dependency.

## 15. Docker/Render smoke test

1. Login as admin/supervisor; create A→B dependency; move A forward so B
   shifts → bell shows a schedule notification for supervisors/admins.
2. As admin, issue an invoice (milestone → SENT) → the assigned client sees a
   payment-request notification.
3. As procurement, consume inventory below reorder threshold → procurement
   sees a low-stock notification.
4. Assign a supervisor to a project → that user sees a "project access"
   notification.
5. Open a notification → navigates to the project; mark read → unread count
   decrements.
6. Client logs in → sees only their own feed; cannot see other users'
   notifications; project timeline still read-only.
7. Refresh → notifications persist (DB-backed).

## 16. Documentation changes

- `docs/M13_IMPLEMENTATION_REVIEW.md` (post-implementation canonical record).
- `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md` (M13
  DONE, notification types, test counts).
- Do **not** modify any prior plan/review docs.

## 17. Expected files

- `backend/app/models/notification.py` (new) + `models/__init__.py` export
- `backend/alembic/versions/<rev>_m13_notifications.py` (new)
- `backend/app/schemas/notification.py` (new)
- `backend/app/services/notifications.py` (new)
- `backend/app/api/v1/notifications.py` (new) + `api/v1/router.py` (register)
- Hooks: `api/v1/tasks.py`, `api/v1/invoicing.py`, `api/v1/inventory.py`,
  `api/v1/projects.py`
- `backend/tests/test_notifications.py` (new)
- `frontend/src/components/NotificationsBell.tsx` (new) + `AppShell.tsx`,
  `frontend/src/lib/api.ts`, `frontend/src/types/index.ts`
- Docs as in §16

## 18. Non-goals

- **Email/SMS/web-push delivery** (external integration; owner decision —
  deferred; would need a provider + P4.3 secrets).
- **7-day low-stock demand forecast** (Phase 5; needs worker).
- Vendor entity / vendor-specific notifications (no vendor model yet; Phase 5).
- Notification preferences/settings page (deferred).
- Retention/cleanup jobs (deferred; rows are small at this scale).
- Any Phase 4 infrastructure (workers, Redis, observability).

## 19. Owner decisions

1. **Delivery channel:** in-app only (recommended, no infra) vs also email
   (deferred; needs provider + secrets).
2. **Notification types in v1:** schedule-shift, invoice-issued, low-stock,
   project-assigned (recommended) — include task-completed? (defer).
3. **Admin recipients:** admins receive operational notifications
   (schedule/stock) but not client invoice notifications (recommended) vs all.
4. **Low-stock alert basis:** static reorder threshold (recommended for v1;
   7-day forecast Phase 5).
5. **Low-stock dedupe:** one notification per (user, project, item) crossing,
   created only when it transitions from above→at/below threshold
   (recommended) vs on every movement.
6. **Mark-read model:** per-notification read + "mark all read" (recommended).
7. **Audit of notification creation:** none (recommended) vs a `notification`
   audit row for invoice-issued only.

## 20. Implementation sequence

1. Migration + model + schema.
2. Service (`create_notifications`, recipient resolution).
3. API (feed, unread-count, read/read-all) + router registration.
4. Hook the four event sites.
5. Tests (service, API, hooks, RBAC, concurrency, regression).
6. Frontend bell + panel + api/types.
7. Full suite + gates + migration test.
8. Docs + Render smoke + review.

## 21. Self-review

- **Dependencies:** only M12/M5/M2/M8 events (all done); no Phase 4; no new
  infra. ✓
- **Scope:** in-app only, event-driven, no worker; email and forecast deferred
  explicitly. ✓
- **RBAC/security:** notifications are user-scoped with owner-only reads and
  404 on foreign IDs; recipient roles mirror existing RBAC; no new auth; M6
  client boundary untouched. ✓
- **Concurrency/atomicity:** notifications commit with their event; no partial
  notifications; mark-read idempotent. ✓
- **Migration:** one additive table with a clean downgrade; no changes to
  existing tables. ✓
- **Regression:** hooks are additive; full suite + client-portal + baseline
  gates cover existing behavior. ✓
- **Owner decisions:** all explicit in §19 (in-app vs email, types, admin
  recipients, low-stock basis/dedupe, mark-read, audit). ✓
- **Demo:** smoke steps in §15 are fully achievable on the current Render/dev
  stack without Phase 4. ✓

**Unresolved owner decisions:** §19 items 1–7.

**Recommendation:** proceed with M13 — Notifications & Alerts (in-app,
event-driven) as the next feature milestone; email delivery and the 7-day
low-stock forecast remain deferred per Phase 5/owner decisions.
