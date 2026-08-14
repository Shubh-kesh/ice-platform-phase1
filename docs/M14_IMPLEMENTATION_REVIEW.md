# M14 — Vendors & Purchase Orders: Implementation Review

**Status:** IMPLEMENTED + VERIFIED (pending owner review; nothing committed).
**Date:** Aug 14, 2026.
**Plan:** `docs/M14_IMPLEMENTATION_PLAN.md` (canonical; not modified).
**Branches/commits:** work on `claude-development`; HEAD was `36f166d`; nothing
committed by this implementation.
**Alembic head:** `k4c5d6e7f8a9` (M14) — repo + DB in sync; migration chain
(upgrade → downgrade → replay) green.

---

## 1. What was implemented

The M14 plan §1–§24, exactly as scoped:

- **Vendor master data** (global, not project-scoped): `vendors` table with
  unique `name` (app 409 + `uq_vendors_name` backstop), `is_active` soft
  deactivation (no hard delete), audit rows (`vendor_create`, `vendor_update`),
  RBAC admin + procurement only, M8 idempotency-protected POST.
- **Purchase orders**: `purchase_orders` + `po_lines` tables, `POStatus` enum.
  `PO-{project_code}-{seq:04d}` numbering allocated inside the project row lock
  (`uq_purchase_orders_po_number` backstop). Server-derived totals —
  `line_total = round(qty × price, 2)`, `subtotal = Σ line_total`,
  `tax_amount = round(subtotal × tax_rate / 100, 2)`, `total_amount` =
  denormalized subtotal + tax, recomputed by `refresh_po_total` in the same
  transaction as every line/header mutation.
- **Lifecycle state machine** (no status PATCH): DRAFT → submit (≥1 line) →
  PENDING_APPROVAL → approve (admin) → APPROVED; reject (admin, reason
  required) → REJECTED → revise → DRAFT or resubmit → PENDING_APPROVAL; cancel
  DRAFT/PENDING (admin+procurement) or APPROVED (admin only). APPROVED and
  CANCELLED are terminal in M14. Header/line edits are DRAFT-only.
- **Project-lifecycle gating**: POs writable on DRAFT/PLANNING/ON_HOLD/ACTIVE;
  COMPLETED freezes (400); ARCHIVED read-only (403 via
  `assert_project_writable`); A/P reads on archived remain.
- **Idempotency (M8 reused)**: `POST /vendors`, `POST …/purchase-orders`
  (incl. nested lines), `POST …/purchase-orders/{po}/lines` protected; retries
  replay the stored response; transitions/PATCH/DELETE deliberately unprotected.
- **Notifications (M13 extended)**: `po_submitted` → all active admins;
  `po_approved` / `po_rejected` → PO creator + all active admins. Fired
  atomically with the transition (rolled-back transition → no notification,
  tested).
- **Frontend**: `VendorsPanel` (Command Center, admin+procurement) and
  `PurchaseOrdersPanel` (ProjectDetail, admin+procurement, frozen on
  COMPLETED/ARCHIVED) with create/edit/deactivate, PO create (nested lines +
  optional tax), DRAFT line add/edit/remove, and all lifecycle actions
  role-gated; types + `api.ts` extended; `NotificationType` extended.

## 2. Files changed

**Backend (new):**
- `backend/alembic/versions/k4c5d6e7f8a9_m14_vendors_purchase_orders.py`
- `backend/app/models/vendor.py`, `backend/app/models/purchase_order.py`
- `backend/app/schemas/vendor.py`, `backend/app/schemas/purchase_order.py`
- `backend/app/services/purchase_orders.py`
- `backend/app/api/v1/vendors.py`, `backend/app/api/v1/purchase_orders.py`
- `backend/tests/test_vendors.py`, `backend/tests/test_purchase_orders.py`
- `backend/scripts/m14_smoke.py`, `backend/scripts/m14_smoke_prep.py`
  (dev-only live-HTTP smoke harness)

**Backend (modified):**
- `backend/app/models/__init__.py` (exports)
- `backend/app/models/notification.py` (+3 `NotificationType` values)
- `backend/app/services/notifications.py` (+3 PO hooks)
- `backend/app/services/idempotency.py` (M8 latent-bug fix, see §9)
- `backend/app/api/v1/router.py` (+2 routers)
- `backend/tests/test_migrations.py` (head → `k4c5d6e7f8a9`; tables asserted)
- `backend/tests/test_notifications.py` (+6 PO notification tests)

**Frontend (new):** `frontend/src/components/VendorsPanel.tsx`,
`frontend/src/components/PurchaseOrdersPanel.tsx`
**Frontend (modified):** `frontend/src/types/index.ts`, `frontend/src/lib/api.ts`,
`frontend/src/pages/CommandCenter.tsx`, `frontend/src/pages/ProjectDetail.tsx`

**Docs:** `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md`,
`docs/M14_IMPLEMENTATION_REVIEW.md` (this file). The prior session's uncommitted
`docs/AI_CONTEXT.md` / `CURRENT_STATE.md` / `SESSION_HANDOFF.md` edits were
preserved (not reverted); `AI_CONTEXT.md` and `SESSION_HANDOFF.md` left as-is.

## 3. API endpoints implemented

Vendors (`/api/v1/vendors`): `GET` (list, by name), `POST` (create, idem),
`GET /{vendor_id}`, `PATCH /{vendor_id}` (incl. `is_active` soft deactivate).

Purchase orders (`/api/v1/projects/{project_id}/purchase-orders`):
`GET` (list, newest first), `POST` (create + nested lines, idem),
`GET /{po_id}`, `PATCH /{po_id}` (DRAFT header), `POST /{po_id}/submit`,
`POST /{po_id}/approve`, `POST /{po_id}/reject` (reason), `POST /{po_id}/revise`,
`POST /{po_id}/resubmit`, `POST /{po_id}/cancel`,
`POST /{po_id}/lines` (idem), `PATCH /{po_id}/lines/{line_id}`,
`DELETE /{po_id}/lines/{line_id}` (204).

## 4. RBAC behavior

- Vendors + POs: admin and procurement only. Supervisors/clients get 403 on
  every vendor/PO route (test-pinned; no client/supervisor PO shape exists).
- Approve / reject / cancel-of-APPROVED: **admin only** (procurement 403).
- Every other PO action (create, header/line edit, submit, revise, resubmit,
  cancel of DRAFT/PENDING) and all vendor ops: admin + procurement.
- PO reads/writes are project-scoped via `get_project_or_404` +
  `assert_project_writable`; cross-project PO/line ids → 404 (IDOR).

## 5. Lifecycle / state-machine behavior

- All transitions row-locked (project lock first, then the PO row
  `SELECT … FOR UPDATE`) and audited (`po_submit`, `po_approve`, `po_reject`,
  `po_revise`, `po_resubmit`, `po_cancel`) with old→new status + attribution.
- Illegal moves → 400 (submit without lines, approve/reject before submit,
  double transitions, revise/resubmit on non-REJECTED, cancel of non-cancelable
  states, header/line edits on non-DRAFT); reject without reason → 422.
- APPROVED/CANCELLED terminal in M14; `revise` returns REJECTED→DRAFT and the
  rejection reason remains on the row as history.

## 6. Totals calculation behavior

- Decimal throughout (`ROUND_HALF_UP`, 2dp) in `services/purchase_orders.py`;
  floats only at the API boundary.
- `total_amount` is stored and recomputed transactionally; invariant
  `total_amount == Σ line_total + tax_amount` asserted after every line
  add/edit/delete and tax-rate PATCH (test-pinned, incl. a real two-session
  concurrent line-add test → total never drifts).

## 7. Idempotency behavior

- Protected POSTs reuse M8: replay returns the stored body verbatim (same PO,
  totals untouched); different-body reuse → 409; failed attempts free the key
  (tested with per-request sessions); concurrent same-key → exactly one PO and
  one `idempotency_records` row (tested with real separate sessions).
- PO-create idempotency serialization uses a small relationship-safe finalizer
  (`_finish_idempotency_po_create`) because `IdempotencyGuard.finish()`'s
  internal `db.refresh()` expires the loaded `lines` relationship, which would
  lazy-load during async serialization (MissingGreenlet). The finalizer writes
  only the record's public columns; M8's service is otherwise untouched.

## 8. Notification behavior

- `po_submitted` → all active admins; `po_approved`/`po_rejected` → PO creator
  (if still active) + all active admins. No supervisors/clients.
- Atomic with the transition (a 400 illegal transition rolls back its would-be
  notification — tested). Each distinct transition fires once (resubmit fires a
  fresh `po_submitted` — tested). M8 replay cannot re-run a transition.

## 9. Deviations from the plan

1. **M8 latent-bug fix (required by M14's acceptance criteria):**
   `app/services/idempotency.py` `claim_idempotency` now snapshots
   `actor_id = user.id` before the claim flush. The same-key loser's
   `db.rollback()` expires loaded objects; the old code re-read `user.id`
   afterwards, and that sync attribute access lazy-loads in async →
   MissingGreenlet (a 500). M8's own concurrent test never reached this branch
   (its winner commits fast enough); M14's required concurrent same-key create
   race does. This is a pre-existing defect, not an M14 regression; the fix is
   behavior-preserving and all 14 M8 tests remain green.
2. **Smoke harness scripts** (`backend/scripts/m14_smoke*.py`) were added beyond
   the plan's "expected files" list as the reproducible live-HTTP smoke tool;
   they are dev-only, outside `app/`/`tests/`, and do not affect lint gates.
3. **Post-independent-review hardening (from the independent review):** the
   vendor `PATCH` rename path now catches the `IntegrityError` on flush and
   returns 409 (was a narrow 500 race under concurrent renames); `delete_po_line`
   snapshots `line.description` before the delete instead of reading the
   flushed-deleted instance; a new test pins the add-line key reuse with a
   different body → 409. No behavior change to the plan's contract.
4. **No other deviations.** The plan's migration filename, revision id
   (`k4c5d6e7f8a9`), enum pattern, lock ordering, RBAC matrix, notification
   recipients, and lifecycle gating were followed verbatim.

## 10. Verification

- **Backend tests:** 307 passing (`pytest tests/ -v`; baseline 256 → 307):
  13 vendor, 32 purchase-order, 18 notification (12 + 6), migration chain
  through `k4c5d6e7f8a9`. Full M1–M13 regression green.
- **Concurrency (real separate DB sessions):** two concurrent PO creates →
  distinct `po_number`s; concurrent same-key create → one PO + one claim row;
  concurrent line adds → `total` never drifts from Σ lines.
- **Quality gates:** ruff 2/2, mypy 10/10, oxlint 1/1 baseline-delta gates PASS
  (zero new findings). Frontend `npm run build` (tsc + vite) and `npm run lint`
  clean (1 pre-existing `auth-context.tsx` Fast-Refresh warning). `git diff
  --check` clean.
- **Live HTTP smoke (uvicorn :8011 + scratch Postgres, 4 role users + ACTIVE
  project):** 27/27 checks green — vendor CRUD + deactivate/reactivate +
  duplicate 409, S/C 403, PO create (nested lines + 18% tax) →
  `PO-PRJ-2026-9001-0001` with correct total, submit → admin notified,
  procurement-approve 403, admin approve → creator+admin notified, procurement
  cancel-APPROVED 403, admin cancel-APPROVED, reject→revise→edit→submit, line
  edit recomputes total, idempotent create replay, archive → write 403 / read OK.

## 11. Security / IDOR review

- Every vendor/PO endpoint role-gated; approve/reject split per the ROADMAP
  "Admin vs Procurement" requirement. No client/supervisor PO shape exists; no
  client/supervisor PO notifications.
- All PO/line queries filter by `project_id` AND child id → cross-project ids
  return 404 (test-pinned for get/patch/line-add/line-patch/line-delete).
- Totals are server-derived; clients never supply money. Archived projects:
  writes 403 after visibility resolution; reads remain A/P-only.
- Notification bodies carry only PO numbers (no amounts/secrets), matching M13.

## 12. Remaining concerns / follow-ups

- M15/M16 (receiving/verification, multi-location inventory, demand forecast,
  vendor-performance tracking) are not started — per plan, explicit M14
  non-goals. M15 will extend `POStatus` additively and add `received_quantity`/
  `stock_movements.po_line_id`/`job_costs` release.
- The M8 loser-path bug is fixed in the shared service; worth noting in any
  future M8 review that the concurrent same-key race now takes the
  rollback+replay branch reliably under slower winners.
- The idempotency finalizer in the PO module duplicates a small slice of
  `IdempotencyGuard.finish()` (public-column writes only); if M8 ever adds more
  record columns, the PO finalizer would need a matching update.
- Frontend still has no automated/E2E tests (repo-wide, Phase 4 item); the
  two new panels are covered by backend RBAC enforcement, not UI tests.

## 13. Verdict

**SAFE TO COMMIT.** All plan acceptance criteria verified: vendor CRUD +
duplicate 409 + audit; PO numbering + totals/tax invariant (concurrency-tested);
full role-gated lifecycle with illegal-move guards; admin-only approve/reject;
S/C 403 everywhere with no PO notifications; COMPLETED freeze / ARCHIVED
read-only; idempotent replay; atomic single-fire notifications; full regression
suite (307) + migration chain + frontend build/lint + baseline-delta gates +
live smoke (27/27) all green. Independent review found no FAILs (3 LOW items
fixed post-review, §9). Nothing committed.
