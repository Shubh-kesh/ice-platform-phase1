# M14 — Vendors & Purchase Orders: Implementation Plan

**Status:** PLANNED (not implemented). No code, migrations, or commits created.
**Date:** Aug 13, 2026.
**Branches/commits this plan assumes:** M1–M13 + M6 close-out + P4.1 shipped;
Alembic head `j8e9f0a1b2c3` (M13 `notifications`). Phase 4 production
infrastructure (P4.2–P4.6) is intentionally **deferred** — M14 must not depend
on it (no Redis, no workers, no queues).
**Source of truth:** `docs/ROADMAP.md` (Phase 5), `docs/CURRENT_STATE.md`,
`docs/ARCHITECTURE.md`, `docs/PRODUCT_REQUIREMENTS.md` (PRD §3.1, §3.3,
§4.2.3, §4.3.1), and the code. This is the plan; the post-implementation record
belongs in `docs/M14_IMPLEMENTATION_REVIEW.md`.

---

## 1. Objective

Deliver the first Phase 5 procurement milestone: **vendor master data** and
**purchase orders with line items and an audited lifecycle**, as the control
surface for material spend. M14 builds the PO as a *commitment* document
(vendor, project, lines, quantities, prices, cost codes, status) integrated
with the existing RBAC, project lifecycle (M10), audit, idempotency (M8), and
notification (M13) rails. Delivery *verification* and the *release of verified
stock to inventory + job costs* are **explicitly deferred to a later Phase 5
milestone** (the PRD's "admitted to project costs after verified" rule).

## 2. Current repository state relevant to M14 (verified)

- **DB/repo in sync** at Alembic `j8e9f0a1b2c3` (M13). Migration chain is
  chain-tested (`tests/test_migrations.py`, `HEAD_REVISION=j8e9f0a1b2c3`).
- **Finance domain patterns to reuse:**
  - M4 job costs: `services/finance.py` (`refresh_budget_spent`), project row
    lock on every mutation (`_get_project_locked`), denormalized running total
    recomputed in the same transaction. `app/api/v1/finance.py`.
  - M5 invoicing: project row lock for `po_number`-style sequencing
    (`next_invoice_seq`), partial unique-index double-creation guard, per-row
    `SELECT ... FOR UPDATE` for status transitions (`_get_invoice_locked`),
    server-derived amounts (`milestone_amount`), COMPLETED-freeze /
    ACTIVE-gate / ARCHIVED-read-only helpers, admin-owned + procurement
    view-only RBAC, `InvoiceClientRead` restricted shape. `app/api/v1/invoicing.py`.
- **M8 idempotency:** `get_idempotency_guard` dependency + `IdempotencyGuard`
  (`app/api/deps.py`, `app/services/idempotency.py`); protected POSTs replay
  the stored response; transitions intentionally unprotected.
- **M10 lifecycle:** `get_project_or_404`, `get_project_for_update`,
  `assert_project_writable`, `can_access_archived` in
  `app/api/project_access.py`; status transitions are admin-only, audited,
  row-locked.
- **M13 notifications:** `services/notifications.py` (recipient resolution +
  `create_notifications` in the caller's transaction),
  `models/notification.py` `type` is a **constrained String(50)** app-level
  enum — new types require **no migration**; bell + feed UI already shipped.
- **Audit:** `record_audit(db, user_id, action, table_name, record_id, changes)`
  called in the same transaction as every mutation; `audit_logs.action` is
  varchar(100).
- **RBAC:** 4 roles; admin+procurement global visibility, supervisor/client
  assignment-gated; clients are read-only with `assert_not_client` on internal
  surfaces (M6). Finance reads are admin/proc only (M4/M5 precedent).
- **Frontend:** Command Center (`CommandCenter.tsx`) hosts admin-only
  `UsersPanel`; `ProjectDetail.tsx` hosts role-gated panels
  (`InvoicingPanel`, `JobCostsPanel`, `InventoryPanel`) behind
  `canViewFinance`/`canWriteFinance` flags; `lib/api.ts` + `types/index.ts`
  are the single API contract; `NotificationsBell` already renders any
  `NotificationType`.
- **Working tree:** `git status` shows 3 modified docs from a prior session
  (`docs/AI_CONTEXT.md`, `docs/CURRENT_STATE.md`, `docs/SESSION_HANDOFF.md`)
  plus this plan (untracked). HEAD is `36f166d`, branch `claude-development`,
  `alembic heads = j8e9f0a1b2c3`. M14 implementation must leave the 3
  pre-existing doc edits untouched (they belong to the prior session's
  handoff) and must not rely on the tree being clean.

## 3. Exact Phase 5 / PRD requirements

From `docs/ROADMAP.md` Phase 5 and `docs/PRODUCT_REQUIREMENTS.md`:

- PRD §3.1 (Admin): "Product-level configuration, thresholds, cost codes, and
  **vendor master data**."
- PRD §3.3 (Procurement Manager): "Inventory management across locations.
  **Purchase order (PO) creation**, delivery verification, and **vendor
  management**."
- ROADMAP Phase 5 MUST: "Vendor entity (name/contact/payment terms) + vendor
  performance tracking (on-time %, price)."
- ROADMAP Phase 5 MUST: "Purchase Order entity (vendor, lines, quantities,
  project, status) + PO lifecycle."
- ROADMAP Phase 5 SHOULD: "Approval workflow: Procurement creates PO →
  (optional) Admin approve → receive."
- ROADMAP Phase 5 security: "PO amount/tax fields; approve-step RBAC (Admin
  vs Procurement)."
- PRD §4.3.1: "Every expense (labor and material) is tagged to a **Cost
  Code**" — M14 PO lines carry a cost code so M15 receiving can tag the
  material cost correctly.
- PRD §4.2.3 acceptance: "A delivery without successful verification is not
  included in project costing" — **receiving is M15**, so M14 POs must not
  create job costs or stock movements.

## 4. M14 scope

1. **Vendor master data** (global, not project-scoped): CRUD + soft
   deactivation, audit trail, RBAC (admin + procurement).
2. **Purchase orders**: project-scoped, `PO-{PROJECT_CODE}-{seq}` numbering,
   vendor + lines + derived totals, lifecycle state machine
   (DRAFT → PENDING_APPROVAL → APPROVED, with REJECTED/revise/resubmit and
   CANCELLED), audit + notifications.
3. **PO line items**: quantity/unit/unit-price/description/cost-code, line
   total derived server-side, editable only in DRAFT.
4. **Approval workflow** (ROADMAP SHOULD): procurement submits, admin
   approves/rejects.
5. **Integration rails reused**: project row locks, M8 idempotency on POSTs,
   M13 in-app notifications, M10 lifecycle gating, existing audit.

## 5. Explicit non-goals (M14)

- **QR-code / photo delivery verification and receipt** — later Phase 5
  milestone (M15). No `deliveries`/`delivery_lines` tables, no release of
  stock to inventory, no job-cost creation from POs.
- **Multi-location inventory** (warehouse/transit/site) — later Phase 5
  milestone (M16). No `inventory_locations`, no `location_*` columns on
  `stock_movements`, no `po_line_id` on `stock_movements`/`job_costs` yet.
- **7-day low-stock demand forecast** — needs a worker (Phase 4 deferred);
  static reorder-threshold alerts stay as-is.
- **Vendor performance tracking (on-time %, price history)** — requires
  delivery history (M15). Schema reserves nothing; M15 adds it.
- **Cross-project inventory roll-up for procurement** — NICE TO HAVE, later.
- **Modification of M4/M5/M6/M8/M10/M13 behavior** — additive only.
- **Any Phase 4 infrastructure** — no Redis, workers, queues, email/push.
- **Hard deletes** — vendors soft-deactivate; POs cancel; lines delete only in
  DRAFT.

## 6. Vendor domain model

Global master data (PRD §3.1 "vendor master data"; §3.3 "vendor management").
Not project-scoped; not visible to supervisors/clients.

**Ownership model (explicit):** a `vendor` is **enterprise-global and shared
across all projects** — it has **no `project_id`**, is created once, and any
project may raise a PO against it. This matches the existing precedence that
admin/procurement see every project (there is no "owning project" for master
data) and avoids duplicating vendor rows per site. Consequences:
- Vendor CRUD is **not** project-scoped and uses only role gates (no
  `assert_can_view_project` — there is no project to check).
- Deactivating a vendor (`is_active=false`) affects future PO creation
  globally but never invalidates or hides existing POs/readability.
- There is no vendor→project ownership, transfer, or sharing model in M14.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `name` | String(255) NOT NULL | unique (`uq_vendors_name`) — app 409 on duplicate |
| `contact_name` | String(255) NULL | |
| `email` | String(255) NULL | format-validated in schema |
| `phone` | String(50) NULL | |
| `payment_terms` | String(255) NULL | e.g. "NET 30" (PRD §3.3 payment terms) |
| `address` | Text NULL | |
| `is_active` | Boolean NOT NULL DEFAULT true | soft deactivation; no hard delete |
| `notes` | Text NULL | |
| `created_at` / `updated_at` | timestamptz | server_default now() |

Deactivation is not destructive: POs referencing a vendor remain readable; PO
**creation** requires an active vendor.

## 7. Purchase-order domain model

Project-scoped commitment document (PRD §4.2.3 "every material delivery is
verified against its PO"; ROADMAP "vendor, lines, quantities, project,
status"). Money `Numeric(14,2)`; quantity `Numeric(12,2)`.

| Field | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `po_number` | String(40) NOT NULL unique (`uq_purchase_orders_po_number`) | `PO-{project_code}-{seq:04d}`, auto |
| `project_id` | FK projects CASCADE NOT NULL | |
| `vendor_id` | FK vendors RESTRICT NOT NULL | can't remove a used vendor |
| `status` | POStatus enum NOT NULL default `draft` | app-level enum; see §9 |
| `order_date` | Date NOT NULL | default today |
| `expected_delivery` | Date NULL | |
| `tax_rate` | Numeric(5,2) NULL | optional; 0–100; single per PO |
| `total_amount` | Numeric(14,2) NOT NULL default 0 | **denormalized** (subtotal + tax), recomputed in same txn |
| `notes` | Text NULL | |
| `created_by` | FK users SET NULL NULL | for notifications (§20) |
| `submitted_at/by`, `approved_at/by`, `rejected_at/by`, `rejected_reason`, `cancelled_at/by` | timestamptz / uuid / Text | attribution columns (M10/M5 precedent) |
| `created_at` / `updated_at` | timestamptz | |

Indexes: `(project_id)`, `(vendor_id)`, `(status)`.

## 8. PO line-item model

| Field | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `purchase_order_id` | FK purchase_orders CASCADE NOT NULL | |
| `description` | String(255) NOT NULL | |
| `quantity` | Numeric(12,2) NOT NULL | > 0 |
| `unit` | String(50) NOT NULL | bags/kg/m3/pcs — same vocabulary as inventory |
| `unit_price` | Numeric(14,2) NOT NULL | ≥ 0 |
| `cost_code` | CostCode enum NOT NULL | **reuses M4 enum** (forward hook for M15 material costs) |
| `created_at` / `updated_at` | timestamptz | |

`line_total` is **derived on read** (`quantity × unit_price`, ROUND_HALF_UP to
2dp) — never stored. Index on `(purchase_order_id)`.

## 9. PO lifecycle / state machine

States: `draft`, `pending_approval`, `approved`, `rejected`, `cancelled`.
(M15 will extend the enum with `partially_received`/`received`/`closed` via an
additive `ALTER TYPE`; not part of M14.)

```
              submit (≥1 line)
   DRAFT ────────────────────────► PENDING_APPROVAL
     │                                 │      │
     │ cancel                          │ approve (admin)
     ▼                                 ▼      │
 CANCELLED ───────────► APPROVED  (terminal in M14)
     ▲                      │
     │ cancel               │ cancel (admin only)
     │                      ▼
     │                  CANCELLED
     │
   PENDING_APPROVAL ──reject (admin, reason required)──► REJECTED
                                                        │
                                        revise ─────────┤
                                            │           │
                                            ▼           ▼
                                          DRAFT    PENDING_APPROVAL (resubmit)
```

- **Freeze semantics:** once `pending_approval` (submitted), header + lines
  are immutable until `rejected`→`revise` returns the PO to DRAFT.
- `approved` and `cancelled` are terminal in M14.
- Transitions are admin- or role-gated (see §10), **row-locked** on the PO
  (and the project), and **audited** — no direct status PATCH.

## 10. RBAC matrix for every vendor/PO operation

Roles: Admin (A), Procurement Manager (P), Site Supervisor (S), Client (C).
S/C never reach these surfaces (403) — the M4/M5 "finance is not a
supervisor/client surface" precedent. Project-scoped PO endpoints additionally
run `get_project_or_404` + archived handling.

**Vendors (global, not project-scoped):**

| Operation | Endpoint | A | P | S | C |
|---|---|---|---|---|---|
| List / get | `GET /vendors`, `GET /vendors/{id}` | ✓ | ✓ | 403 | 403 |
| Create | `POST /vendors` | ✓ | ✓ | 403 | 403 |
| Update / deactivate | `PATCH /vendors/{id}` | ✓ | ✓ | 403 | 403 |

**Purchase orders (project-scoped):**

| Operation | Endpoint | A | P | S | C |
|---|---|---|---|---|---|
| List / get | `GET /projects/{id}/purchase-orders[/{po_id}]` | ✓ | ✓ | 403 | 403 |
| Create (optional nested lines) | `POST /projects/{id}/purchase-orders` | ✓ | ✓ | 403 | 403 |
| Update header (DRAFT) | `PATCH .../purchase-orders/{po_id}` | ✓ | ✓ | 403 | 403 |
| Add / edit / remove line (DRAFT) | `POST/PATCH/DELETE .../lines[/{line_id}]` | ✓ | ✓ | 403 | 403 |
| Submit (DRAFT→PENDING_APPROVAL) | `POST .../{po_id}/submit` | ✓ | ✓ | 403 | 403 |
| Approve (→APPROVED) | `POST .../{po_id}/approve` | ✓ | **✗** | 403 | 403 |
| Reject (→REJECTED, reason required) | `POST .../{po_id}/reject` | ✓ | **✗** | 403 | 403 |
| Revise (REJECTED→DRAFT) | `POST .../{po_id}/revise` | ✓ | ✓ | 403 | 403 |
| Resubmit (REJECTED→PENDING_APPROVAL) | `POST .../{po_id}/resubmit` | ✓ | ✓ | 403 | 403 |
| Cancel DRAFT / PENDING_APPROVAL | `POST .../{po_id}/cancel` | ✓ | ✓ | 403 | 403 |
| Cancel APPROVED | `POST .../{po_id}/cancel` | ✓ | **✗** | 403 | 403 |

The approve/reject separation is the ROADMAP "approve-step RBAC (Admin vs
Procurement)" requirement.

## 11. Project lifecycle constraints

- **Create / line edit / header edit / all transitions** are allowed on
  DRAFT, PLANNING, ON_HOLD and ACTIVE projects — a PO is a *commitment* that
  can be raised during planning (long-lead materials), deliberately more
  permissive than M5's ACTIVE-only invoicing. Flagged as an owner decision
  (§33.3).
- **COMPLETED:** POs are frozen — no create, no line/header edit, no
  transitions (400, mirroring `_assert_milestones_writable` in M5). Reads
  remain available to A/P.
- **ARCHIVED:** read-only everywhere via the shared `assert_project_writable`
  (403 for A/P after visibility resolution). POs remain listable/readable for
  A/P on archived projects (M5 archived-invoice precedent).
- No hard DELETE for vendors or POs (soft lifecycle doctrine, M10).

## 12. Database schema and migration design

**One new additive Alembic revision** `k4c5d6e7f8a9` (after
`j8e9f0a1b2c3`). Three new tables, one new enum, **no changes to existing
tables**:

- `vendors` (per §6; `uq_vendors_name`, `ix_vendors_is_active`).
- `purchase_orders` (per §7; `uq_purchase_orders_po_number`, FKs to projects
  CASCADE / vendors RESTRICT / users SET NULL for attribution, indexes on
  project_id / vendor_id / status).
- `po_lines` (per §8; FK purchase_orders CASCADE, index on purchase_order_id).
- `POStatus` enum: `draft`, `pending_approval`, `approved`, `rejected`,
  `cancelled`. The `cost_code` enum is **reused** from M4 (no new enum).

**Constraints summary:** NOT NULL on every money/quantity/status/po_number
column; `quantity > 0` and `unit_price >= 0` enforced at the schema boundary
(no DB CHECK — consistent with the repo's "no DB CHECK constraints" doctrine);
uniqueness enforced by `uq_vendors_name` and `uq_purchase_orders_po_number`;
FK integrity for project/vendor/attribution.

**Concurrency/locking requirements (see §17 for full strategy):** every PO
mutation runs inside a transaction that first takes the **project row lock**
(`SELECT ... FOR UPDATE`) to serialize po_number allocation and
`total_amount` recomputation, and PO **transitions** additionally take a
**PO row lock** — both held to commit. No new lock granularity is required;
the existing M1/M4/M5/M10 doctrine covers all M14 writes. Vendor writes are
single-row, lock-free (no cross-row derivation).

**Enum migration pattern (must follow M5's migration, `g5b6c7d8e9f0`):**
create the `POStatus` enum explicitly with `sa.Enum(...).create(op.get_bind(),
checkfirst=True)` **before** `op.create_table`, and add enum-backed columns via
`op.add_column` — SQLAlchemy 2.0.35's `op.create_table` re-emits a
non-checkfirst `CREATE TYPE` and fails with DuplicateObject otherwise (the
documented M5 lesson).

**Downgrade (non-destructive):** drop `po_lines`, `purchase_orders`,
`vendors` (constraints/indexes first), then drop the `POStatus` enum. No
existing table is touched, so downgrade never risks pre-existing data.

`test_migrations.py` `HEAD_REVISION` must be updated to `k4c5d6e7f8a9` so the
chain test covers the new revision.

## 13. API endpoint matrix

**Vendors** (`app/api/v1/vendors.py`, prefix `/vendors`):
| Method | Path | RBAC | Notes |
|---|---|---|---|
| GET | `/vendors` | A, P | list (all, `is_active` field present) |
| POST | `/vendors` | A, P | idempotency-protected; 409 on duplicate name |
| GET | `/vendors/{vendor_id}` | A, P | |
| PATCH | `/vendors/{vendor_id}` | A, P | incl. `is_active=false` soft deactivate |

**Purchase orders** (`app/api/v1/purchase_orders.py`, prefix
`/projects/{project_id}/purchase-orders`):
| Method | Path | RBAC | Notes |
|---|---|---|---|
| GET | `` | A, P | list (newest first) |
| POST | `` | A, P | idempotency-protected; optional nested `lines` |
| GET | `/{po_id}` | A, P | |
| PATCH | `/{po_id}` | A, P | DRAFT header fields only |
| POST | `/{po_id}/submit` | A, P | DRAFT→PENDING_APPROVAL; ≥1 line required |
| POST | `/{po_id}/approve` | A | →APPROVED |
| POST | `/{po_id}/reject` | A | →REJECTED; `rejected_reason` required |
| POST | `/{po_id}/revise` | A, P | REJECTED→DRAFT |
| POST | `/{po_id}/resubmit` | A, P | REJECTED→PENDING_APPROVAL |
| POST | `/{po_id}/cancel` | A, P | per §10 matrix |
| POST | `/{po_id}/lines` | A, P | DRAFT only; idempotency-protected |
| PATCH | `/{po_id}/lines/{line_id}` | A, P | DRAFT only; recompute total |
| DELETE | `/{po_id}/lines/{line_id}` | A, P | DRAFT only; recompute total; 204 |

No `DELETE` for vendors or POs (soft lifecycle). PO line deletes are legitimate
DRAFT edits (the line is not yet committed paper).

### 13.1 Error semantics

Uniform FastAPI error shape `{ "detail": ..., "errors": [...] }` (global
handlers already in place — no new handlers):

| Status | Meaning |
|---|---|
| 400 | illegal transition / state-machine violation; line edit on non-DRAFT; frozen COMPLETED project; submit with 0 lines; no `rejected_reason` on reject (or 422 if schema-typed) |
| 403 | role not permitted (S/C on any vendor/PO route; procurement on approve/reject/approve-cancel) |
| 404 | vendor/PO/line not found; cross-project PO id (IDOR — never 403/leak) |
| 409 | duplicate vendor name; duplicate po_number backstop; Idempotency-Key conflict/reuse/expiry |
| 422 | Pydantic field validation (e.g. `quantity <= 0`, `unit_price < 0`, `tax_rate > 100`, bad email) |
| 401 | missing/invalid bearer token (dependency) |

ARCHIVED-project writes return 403 via `assert_project_writable` (for A/P who
can see the project); supervisors/clients never reach these routes, so the
archived-404 trick is unnecessary here.

### 13.2 Pagination

**None for M14.** This matches every existing list endpoint (projects, tasks,
inventory, invoices) and the ~10–15 project scale; vendors/POs per project are
small bounded sets. Cursor/OFFSET pagination on list endpoints is tracked as a
general Phase 4 perf item (`docs/CURRENT_STATE.md` §9) and is explicitly out of
scope. PO lists order by `created_at DESC` (like invoices); vendor lists order
by `name`.

## 14. Request/response schemas

`app/schemas/vendor.py`:
- `VendorCreate` (name, contact_name?, email?, phone?, payment_terms?,
  address?, notes?), `VendorUpdate` (all optional), `VendorRead`
  (from_attributes; includes `is_active`, timestamps).

`app/schemas/purchase_order.py`:
- `POLineCreate` (description, quantity>0, unit, unit_price≥0, cost_code),
  `POLineUpdate` (all optional), `POLineRead` (+ derived `line_total: float`).
- `PurchaseOrderCreate` (vendor_id, order_date?, expected_delivery?,
  tax_rate?, notes?, lines: list[POLineCreate] = []).
- `PurchaseOrderUpdate` (vendor_id?, order_date?, expected_delivery?,
  tax_rate?, notes? — DRAFT only; client can never set money).
- `PurchaseOrderReject` (rejected_reason: str, min 1).
- `PurchaseOrderRead` (from_attributes): id, po_number, project_id,
  **project_code**, vendor_id, **vendor_name**, status, order_date,
  expected_delivery, tax_rate, **subtotal**, **tax_amount**, **total_amount**
  (transient/derived), lines: list[POLineRead], attribution fields, timestamps.

Transient fields follow the `_attach_read_fields` setattr doctrine (M5
`project_code`/`overdue`): `project_code`, `vendor_name`, `subtotal`,
`tax_amount` are computed/attached before serialization; `total_amount` is the
stored denormalized value.

## 15. Validation rules

- **Vendor:** name required ≤255, unique (409); email format when provided;
  no money fields.
- **PO create/update:** vendor exists and `is_active`; project exists and is
  non-frozen (§11); at least one line before submit (submit-time check, 400);
  tax_rate 0–100 when provided; money/quantities never client-derivable.
- **Lines:** quantity > 0; unit_price ≥ 0; description required ≤255; unit
  ≤50; cost_code valid enum; line edits only on DRAFT (400 otherwise).
- **Transitions:** only legal state-machine moves (400 on illegal); reject
  requires reason; line/header edits only on DRAFT; submit requires ≥1 line.
- **Schema boundary (422):** Pydantic `Field` constraints like M5
  (`gt=0`, `ge=0`, `le=100`, `min_length`, `max_length`).
- **IDOR:** every PO/line query filters by `project_id` AND the child id
  (M5 `_get_invoice_locked` pattern) — cross-project ids → 404.

## 16. Server-derived calculations and invariants

Pure-domain math in `app/services/purchase_orders.py` (thin-service pattern,
Decimal throughout, `ROUND_HALF_UP` quantum 0.01):

- `line_total(qty, price) = (qty × price).quantize(0.01, ROUND_HALF_UP)`.
- `subtotal = Σ line_total` (SQL `SUM(quantity * unit_price)` or in-service).
- `tax_amount = round(subtotal × tax_rate / 100, 2)` when tax_rate set,
  else 0.
- `total_amount = subtotal + tax_amount` — **denormalized on
  `purchase_orders.total_amount`**, recomputed by `refresh_po_total(db, po)`
  inside the same transaction as every line create/update/delete and every
  header PATCH that changes `tax_rate`.
- `po_number = PO-{project_code}-{seq:04d}` where `seq` = count of POs for the
  project + 1, computed **inside the project row lock** (the `next_invoice_seq`
  pattern) so concurrent creates serialize; `uq_purchase_orders_po_number` is
  the DB backstop.
- **Invariants (test-pinned):** `purchase_orders.total_amount == subtotal +
  tax_amount` after every line mutation; no line references a different
  project's PO; no PO state can be reached without the audited transition.

## 17. Transaction / concurrency strategy

Follows the M1/M4/M5/M10 row-lock doctrine exactly:

- **All PO mutations** (create, line ops, header PATCH, transitions) take the
  **project row lock** (`get_project_for_update`) first — this serializes
  `po_number` allocation and total recomputation, matching M4 job costs.
- **Transitions additionally lock the PO row** (`SELECT ... FOR UPDATE`,
  `_get_po_locked` — the M5 `_get_invoice_locked` pattern) so two concurrent
  submit/approve/cancel calls can't both pass the same state guard.
- **Lock ordering (deadlock safety):** always acquire **project row first,
  PO row second** (never the reverse, and never a second project's row within
  one transaction). Since every PO mutation locks its own project row and no
  mutation ever locks two projects or two POs across projects, lock graphs
  are acyclic — no deadlock is reachable. Vendor writes lock nothing (no
  cross-row derivation).
- Data change + `total_amount` recompute + audit row (+ any notification) +
  idempotency claim finalization commit **in one transaction**; a failed
  request leaves nothing half-applied.
- `vendors` mutations are single-row writes; no cross-row derivation, so no
  lock required (matches users/project PATCH).

## 18. Idempotency strategy

Reuse M8 unchanged:

- **Protected:** `POST /vendors`, `POST /projects/{id}/purchase-orders`
  (including nested lines), `POST .../{po_id}/lines`. A retry replays the
  stored response (same PO/line, totals untouched); a failed attempt frees the
  key; concurrent same-key requests execute exactly once via the
  `(actor_id, operation, idempotency_key)` unique-index claim ledger.
- **Not protected (M8 doctrine):** transitions (state-machine guarded — a
  retry can't double-mutate), PATCH/DELETE (naturally idempotent).
- Nested-line create: the claim + PO + lines + audit + totals all roll back
  together on failure (same transaction), so the key stays free for a safe
  retry.

## 19. Audit events

`record_audit` in the same transaction; `audit_logs.action` varchar(100)
(M3-widened):

- `vendor_create`, `vendor_update` (incl. `is_active` flip → deactivate).
- `purchase_order_create` (po_number, vendor_id, project_id, total),
  `purchase_order_update` (changed header fields).
- `po_line_add`, `po_line_update`, `po_line_remove` (with total old→new).
- `po_submit`, `po_approve`, `po_reject` (incl. reason), `po_revise`,
  `po_resubmit`, `po_cancel` — each records status old→new + attribution
  (at/by timestamps + actor id), mirroring M5 `invoice_issue`/`invoice_paid`.

No second audit system; notifications are feature rows, not audit events (M13
doctrine).

## 20. Notification events and recipients

New `NotificationType` values (constrained String(50) — **no migration**):
`po_submitted`, `po_approved`, `po_rejected`. New thin hooks in
`app/services/notifications.py` (same transactional pattern as M13):

| Event | Recipients | Rationale |
|---|---|---|
| PO submitted (DRAFT→PENDING_APPROVAL) | all active **admins** | an approval task awaits |
| PO approved | `po.created_by` (if active) + active admins | creator learns of the decision |
| PO rejected | `po.created_by` (if active) + active admins | creator must act (revise/resubmit) |

- Links to `/projects/{project_id}`; bodies minimal (PO number, no money
  beyond what the role sees).
- **Dedupe:** transitions are single-occurrence (state machine), so no
  duplicate notifications; M8 replay never re-runs a transition; a
  rejected→revise→resubmit cycle legitimately fires new `po_submitted`/reject
  events (each is a distinct, audited transition).
- Clients/supervisors never receive PO notifications (they can't see POs).

## 21. Inventory integration boundary

- M14 **does not touch** `inventory_items` or `stock_movements`.
- PO lines carry `unit`, `quantity`, and `cost_code` precisely so the M15
  receipt flow can record RECEIVED movements (+ `po_line_id` added by M15) and
  update `quantity_on_hand` without schema rework.
- Low-stock alerts stay threshold-based (unchanged, M13).

## 22. Job-cost / finance integration boundary

- M14 POs are **commitments, not expenditures**: no `job_costs` rows, no
  change to `Project.budget_spent`, no effect on M4 budget rollup or M5
  invoicing. This honors PRD §4.2.3 ("a delivery without successful
  verification is not included in project costing" — verification is M15).
- The `cost_code` on every PO line is the forward-integration hook so M15
  receiving creates the material `JobCost` with the correct M4 cost code
  (PRD §4.3.1).
- M4/M5 endpoints and their tests are untouched.

## 23. Frontend UX and affected components

- **`components/VendorsPanel.tsx` (new):** vendor list + create/update form +
  soft-deactivate toggle. Rendered in the Command Center for
  admin+procurement (mirrors how `UsersPanel` sits in the Command Center,
  but role-gated A/P not admin-only).
- **`components/PurchaseOrdersPanel.tsx` (new):** per-project PO list (number,
  vendor, status badge, total), create-PO form (vendor select, order/expected
  dates, optional tax rate, notes, line editor with description/quantity/unit/
  unit-price/cost-code), DRAFT line add/edit/remove, submit/approve/reject
  (reason prompt)/revise/resubmit/cancel actions. Rendered in `ProjectDetail`
  for admin+procurement behind the existing `canViewFinance` /
  `canWriteFinance` flags; frozen (read-only) on COMPLETED/ARCHIVED.
- **`pages/CommandCenter.tsx` / `pages/ProjectDetail.tsx`:** wire the two new
  panels with the established role flags; invalidate `["purchase-orders", id]`
  and `["vendors"]` query keys on mutation.
- **`lib/api.ts`:** vendor + PO + line + transition functions (mirror the M5
  invoicing helpers).
- **`types/index.ts`:** `Vendor`, `VendorCreateInput`, `PurchaseOrder`,
  `PurchaseOrderCreateInput`, `PurchaseOrderLine`, `POLineCreateInput`,
  `PurchaseOrderStatus`, `PurchaseOrderRejectInput`, and extend
  `NotificationType` with `"po_submitted" | "po_approved" | "po_rejected"`.
- **`NotificationsBell`:** no change required (renders any type generically).
- No new UI library; reuse ink/blueprint Tailwind theme and the existing
  panel/form patterns.

### 23.1 Role gating

Mirror the `ProjectDetail` flags exactly: panels render only for
`admin | procurement_manager` (`canViewFinance`/`canWriteFinance`); frozen to
read-only on COMPLETED/ARCHIVED (`isArchived` + project status); never rendered
for supervisors/clients (the API 403s regardless — UI is presentation only).

### 23.2 Loading / error / empty states

Follow the `InvoicingPanel` conventions (Loader2 spinner, error banner,
empty-state copy) — no new UI kit:

- **Loading:** `<Loader2 className="animate-spin" />` + muted label while the
  vendors / PO list query is pending.
- **Error:** inline banner (existing `getErrorMessage` helper in the panel
  files) surfacing the API `detail` for create/update/transition failures;
  keep the form open so the user can retry.
- **Empty:** "No vendors yet. Add your first vendor to create purchase orders."
  / "No purchase orders yet. Create a PO to start committing material spend."
- **Action states:** disable buttons while a mutation is pending; show the
  resulting status badge per PO (draft / pending_approval / approved /
  rejected / cancelled) like `invoiceStatusBadge`.

## 24. Security / IDOR / data-leakage analysis

- **Role gating:** every vendor/PO endpoint uses `require_role(ADMIN,
  PROCUREMENT_MANAGER)` (transitions split further in §10). Supervisors and
  clients get 403 — no client/supervisor PO shape exists (M6 boundary
  preserved: clients remain read-only and never see internal spend).
- **IDOR:** PO and line queries always filter by `project_id` + child id →
  cross-project access 404s (M5 doctrine). Vendors are global master data
  (not project-scoped) — role gate is the only control, which is correct.
- **Archived projects:** `assert_project_writable` → 403 for writes;
  A/P reads on archived remain (M5 precedent); supervisors/clients never reach
  these routes at all.
- **Money fields:** totals are server-derived and stored; clients never
  supply money; `total_amount`/`subtotal` only ever serialize to A/P.
- **Notifications:** recipient resolution reuses existing role data; no new
  authorization surface; no secrets/PII in bodies (M13 doctrine).
- **No client-exposed PO numbers/amounts**, so the DRAFT-invoice-style
  hidden/404 pattern is unnecessary (clients can't reach the routes).
- Rate limiting: no new public endpoints (all bearer-gated), consistent with
  existing app traffic.

## 25. Test strategy

- `tests/test_vendors.py` (new): CRUD, duplicate-name 409, email validation,
  soft deactivation, audit rows, RBAC (S/C 403), idempotent create replay.
- `tests/test_purchase_orders.py` (new):
  - po_number format + per-project sequencing + uniqueness backstop.
  - line ops + `total_amount == subtotal + tax` invariant on every mutation.
  - Full state machine: legal/illegal transitions (submit with 0 lines → 400,
    approve before submit → 400, reject without reason → 422/400, cancel
    terminal, revise/resubmit).
  - RBAC matrix per §10 (approve/reject admin-only; procurement 403; S/C 403).
  - Lifecycle gating: COMPLETED frozen (400), ARCHIVED write 403, archived
    read OK for A/P.
  - Idempotency: create-PO and add-line replay verbatim; different-body 409.
  - Concurrency (real **separate DB sessions/connections** — the M1/M12
    doctrine, e.g. two `async_sessionmaker` sessions on the same engine):
    two concurrent creates → distinct po_numbers (project row lock);
    concurrent same-key create → exactly one PO, one idempotency row;
    concurrent line edits (add + add on different connections) → total never
    drifts from Σ lines.
  - IDOR: PO/line of another project → 404.
  - Audit events per action; notifications created atomically (rollback
    leaves none).
- `tests/test_notifications.py`: add `po_submitted`→admins, `po_approved`/
  `po_rejected`→creator+admins, dedupe on a single transition, none to
  supervisors/clients.
- `tests/test_migrations.py`: update `HEAD_REVISION` to `k4c5d6e7f8a9`;
  upgrade/downgrade/replay chain must pass (incl. enum drop on downgrade).
- **Regression against all M1–M13 tests:** the full backend suite (256 today)
  must stay green — auth/M9, Google/M11, client-portal/M6, health/M3,
  lifecycle/M10, finance/M4, invoicing/M5, idempotency/M8, notifications/M13,
  task-scheduling/M12, inventory/M1, migration chain; plus frontend
  `npm run build` + `npm run lint` and CI baseline-delta gates (ruff 2 /
  mypy 10 / oxlint 1 must not grow).

## 26. Migration / rollback strategy

- **Up:** apply `k4c5d6e7f8a9` (additive — new tables only).
- **Rollback:** revert code (models, schemas, services, routers, hooks,
  frontend) then `alembic downgrade k4c5d6e7f8a9` (or `-1`) — drops the three
  new tables + POStatus enum non-destructively. No existing table/data is
  affected in either direction.
- No data backfill needed (new tables start empty; seed/demo data not
  extended in M14 — seed gains vendors/POs only if a demo wants them, and the
  demo flag remains gated; see §33.7).

## 27. Render / demo smoke-test plan

1. **Login as procurement** (`procurement@ice.demo` demo account or a test
   user) → Command Center shows the Vendors section; create a vendor, then
   soft-deactivate and reactivate it.
2. Create a PO on an ACTIVE project with 2 lines (different cost codes, units,
   prices) and an optional tax rate → PO number renders `PO-{code}-0001`, the
   total = Σ lines + tax; submit → status `pending_approval`, lines frozen.
3. **Login as admin** → approve the PO; the procurement creator's bell shows a
   `po_approved` notification; reject a second PO with a reason → creator sees
   `po_rejected`; revise it back to DRAFT and edit a line → total recomputes.
4. Cancel a DRAFT PO as procurement and an APPROVED PO as admin.
5. As **supervisor** and as **client**: confirm 403/no PO surface and no PO
   notifications in the bell; client portal behavior unchanged.
6. Archive the project → confirm POs read-only (403 on write) but still
   listable for A/P.
7. Reload → PO state persists (DB-backed); audit log shows the full transition
   history for the PO.

## 28. Documentation changes

- `docs/M14_IMPLEMENTATION_REVIEW.md` (post-implementation canonical record).
- `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md` (M14
  DONE, PO state machine, vendor/PO test counts, deferral of M15/M16).
- Do **not** modify prior plan/review docs. Leave the 3 currently-uncommitted
  docs (AI_CONTEXT/CURRENT_STATE/SESSION_HANDOFF) from the prior session as-is.

## 29. Expected files

Backend:
- `backend/alembic/versions/k4c5d6e7f8a9_m14_vendors_purchase_orders.py` (new)
- `backend/app/models/vendor.py` (new) + `models/__init__.py` export
- `backend/app/models/purchase_order.py` (new) + `models/__init__.py` export
- `backend/app/schemas/vendor.py` (new)
- `backend/app/schemas/purchase_order.py` (new)
- `backend/app/services/purchase_orders.py` (new — line_total/subtotal/tax/
  total math, po_number sequencing, refresh_po_total)
- `backend/app/services/notifications.py` (3 new notification types + hooks)
- `backend/app/api/v1/vendors.py` (new) + `api/v1/router.py` registration
- `backend/app/api/v1/purchase_orders.py` (new) + `api/v1/router.py`
  registration
- `backend/tests/test_vendors.py`, `backend/tests/test_purchase_orders.py`
  (new); `backend/tests/test_notifications.py` (extend);
  `backend/tests/test_migrations.py` (HEAD_REVISION update)

Frontend:
- `frontend/src/components/VendorsPanel.tsx` (new)
- `frontend/src/components/PurchaseOrdersPanel.tsx` (new)
- `frontend/src/pages/CommandCenter.tsx`, `frontend/src/pages/ProjectDetail.tsx`
- `frontend/src/lib/api.ts`, `frontend/src/types/index.ts`

Docs: `docs/M14_IMPLEMENTATION_REVIEW.md` (post), plus §28 updates.

## 30. Implementation sequence

1. Migration `k4c5d6e7f8a9` + update `test_migrations.py` HEAD.
2. Models (`vendor.py`, `purchase_order.py`) + `models/__init__.py` exports.
3. Schemas (`vendor.py`, `purchase_order.py`).
4. Service `purchase_orders.py` (pure math + po_number + refresh_po_total).
5. `api/v1/vendors.py` + registration.
6. `api/v1/purchase_orders.py` (CRUD, lines, transitions) + registration.
7. Notification types + hooks in `services/notifications.py`.
8. Tests: vendors, purchase orders, notifications extensions, migrations.
9. Frontend: types → api.ts → `VendorsPanel` → `PurchaseOrdersPanel` →
   wiring in CommandCenter/ProjectDetail.
10. Full suite + quality gates + migration chain.
11. Docs + Render smoke + review.

## 31. Acceptance criteria

- Admin/procurement can create, edit, soft-deactivate vendors; duplicate names
  → 409; every vendor write is audited.
- A PO can be created (with or without nested lines), gets `PO-{project_code}
  -{seq}` numbering, and its total always equals Σ(line totals) + optional
  tax — the invariant holds under concurrent line edits.
- The PO lifecycle walk DRAFT → PENDING_APPROVAL → APPROVED (and REJECTED →
  revise/resubmit, and cancel from the legal states) works only through the
  audited, role-gated transitions; illegal moves → 400.
- Approve/reject are **admin-only**; procurement cannot approve.
- Supervisors and clients get 403 on every vendor/PO endpoint and no PO
  notifications.
- COMPLETED projects freeze POs; ARCHIVED projects are read-only; archived POs
  remain readable by A/P.
- Idempotency: a retried PO-create or line-add replays, never duplicates.
- Notifications: submitted→admins, approved/rejected→creator+admins, atomic
  with the transition.
- No change to M4/M5/M6/M8/M10/M13 behavior; full backend suite + migration
  chain + frontend build/lint green; ruff/mypy/oxlint baselines unchanged.
- No Phase 4 infrastructure introduced; receiving/verification (M15),
  multi-location inventory (M16), and demand forecast (M16) are untouched.

## 32. Regression risks

- **M4/M5/M8/M13 behavior:** all additions are new routes/services; hooks are
  additive. Full suite + client-portal (M6) + invoicing + finance + inventory +
  notifications suites pin existing behavior.
- **Route registration order:** new routers appended to `router.py` (no
  conflicting `/projects/{id}` path params; PO prefix is distinct).
- **Notification type union:** `models/notification.py` (app-level String
  enum) + `types/index.ts` `NotificationType` must be extended **together** —
  the frontend union and backend serializer are the two places new types
  surface.
- **Baseline gates:** new code must add zero ruff/mypy findings (Decimal +
  enum handling is the usual tripwire — follow `finance.py`/`invoicing.py`
  typing).
- **Enum migration pitfall:** M5's non-checkfirst `CREATE TYPE` lesson must be
  followed (§12) or the migration fails on upgrade.
- **`next_invoice_seq`-style counting:** po_number seq must be computed under
  the project row lock to avoid the lost-update race M1 fixed for inventory.
- **Existing uncommitted doc edits:** leave untouched.

## 33. Owner decisions

1. **Approval mandatory vs optional:** M14 makes submission→admin-approval the
   only path to APPROVED (recommended; matches the ROADMAP SHOULD and gives
   clean audit). Optional auto-approve bypass is deferred.
2. **PO lifecycle gating:** POs creatable on DRAFT/PLANNING/ON_HOLD/ACTIVE,
   frozen at COMPLETED/ARCHIVED (recommended — planning-time commitments).
   Stricter ACTIVE-only is the alternative.
3. **Tax fields:** include a single optional PO-level `tax_rate` with derived
   tax_amount/total (recommended — ROADMAP Phase 5 security lists "PO
   amount/tax fields"). Per-line tax is deferred.
4. **Vendor uniqueness:** unique vendor `name` (recommended — small-org master
   data; 409 on duplicate) vs allow duplicate names.
5. **Notification recipients:** submitted→admins; approved/rejected→created_by
   + admins (recommended). Alternative: all active procurement managers +
   admins (global-role, like low-stock).
6. **Cancel RBAC:** procurement cancels DRAFT/PENDING_APPROVAL; admin also
   cancels APPROVED (recommended).
7. **Seed/demo data:** M14 adds no demo vendors/POs by default; optional gated
   demo entries if a demo needs them (keep `ICE_SEED_DEMO` gate).

## 34. Explicit deferred items

- **QR/photo delivery verification + receipt → stock/costing** (M15): needs
  `deliveries`/`delivery_lines`, `received_quantity` on lines,
  `stock_movements.po_line_id`, `job_costs` creation, and POStatus
  `partially_received`/`received`/`closed` (additive `ALTER TYPE`).
- **Multi-location inventory** (M16): `inventory_locations`,
  `stock_movements.location_from/to`, warehouse/transit/site queries.
- **7-day low-stock demand forecast** (M16; needs a worker).
- **Vendor performance tracking (on-time %, price history)** — blocked on M15
  delivery data.
- **Cross-project inventory roll-up** (Phase 5 NICE TO HAVE).
- **Email/SMS/web-push delivery** (external provider + secrets).
- **Frontend automated/E2E tests** (Phase 4).

## 35. Self-review

- **RBAC/IDOR gaps:** every vendor/PO endpoint role-gated (A/P; approve/reject
  admin-only); PO/line queries project-scoped → cross-project 404; supervisors/
  clients never reach any route and never receive PO notifications; no new
  client shape exists. ✓
- **PO state-transition loopholes:** state machine is the single status
  authority (no status PATCH); line/header edits frozen outside DRAFT; terminal
  states (`approved`/`cancelled`) have no outgoing edges in M14; rejections
  require a reason; transitions row-locked on PO + project. ✓
- **Concurrent PO mutation issues:** project row lock serializes po_number
  allocation and total recomputation; per-row PO lock for transitions; no
  drift possible (invariant test + concurrent test). ✓
- **Incorrect total calculations:** Decimal math with ROUND_HALF_UP; totals
  server-derived and recomputed in-transaction; invariant test pins
  `total == Σ lines + tax`. ✓
- **Duplicate PO/line creation:** unique `po_number` + project-lock sequencing;
  M8 idempotency on create/line-add (replay, not re-execute). ✓
- **Archived/DRAFT project behavior:** COMPLETED frozen (400), ARCHIVED
  read-only (403), reads OK for A/P on archived; DRAFT/PLANNING/ON_HOLD/ACTIVE
  writable per §11. ✓
- **Client data leakage:** no client route or shape; no client notifications;
  M6 portal tests untouched and must stay green. ✓
- **Notification duplication:** transitions are single-fire; M8 replay can't
  re-run transitions; each distinct transition legitimately notifies once. ✓
- **Audit completeness:** every create/update/line/transition records an audit
  row atomically with the change; attribution columns mirror M5. ✓
- **Interaction with M8:** protected POSTs reuse the existing guard verbatim;
  transitions deliberately unprotected (state machine, M8 doctrine). ✓
- **Interaction with M5/M4 finance:** M14 POs create no job costs and touch no
  budgets/invoices; the `cost_code` line field is the forward hook only;
  M4/M5 tests unchanged. ✓
- **Unnecessary database migrations:** exactly one additive migration (3 new
  tables, 1 new enum, no existing-table changes); notification types need no
  migration (String(50)); M15 adds its own columns. ✓
- **Scope creep into later Phase 5 milestones:** verification/receiving,
  locations, forecast, and vendor-performance are explicitly non-goals (§5/§34);
  the ROADMAP SHOULD (approval workflow) is in scope and correctly role-gated. ✓
- **Frontend regressions:** panels gated behind existing role flags; query-key
  invalidation follows the InvoicingPanel pattern; no new library. ✓

**Recommendation:** proceed with M14 — Vendors & Purchase Orders, scoped to
commitments + lifecycle + approval workflow, with receiving/verification,
multi-location inventory, and demand forecasting as later Phase 5 milestones.
