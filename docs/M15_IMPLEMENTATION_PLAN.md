# M15 — PO Delivery Verification / Receiving: Implementation Plan

**Status:** PLANNED (not implemented). No code, migrations, or commits created.
**Date:** Aug 14, 2026.
**Branches/commits this plan assumes:** M1–M14 + M6 close-out + P4.1 shipped; Alembic head
`k4c5d6e7f8a9` (M14 `vendors`/`purchase_orders`/`po_lines`); backend baseline **307 passing**;
frontend `npm run build` + `npm run lint` green; ruff 2 / mypy 10 / oxlint 1 baseline-delta gates.
Phase 4 production infrastructure (P4.2–P4.6) is intentionally **deferred** — M15 must not depend
on it (no Redis, no workers, no queues, no GCS signed uploads, no email/push).
**Source of truth:** `docs/AI_CONTEXT.md`, `docs/SESSION_HANDOFF.md`, `docs/CURRENT_STATE.md`,
`docs/ROADMAP.md`, `docs/M14_IMPLEMENTATION_PLAN.md`, `docs/M14_IMPLEMENTATION_REVIEW.md`,
`docs/PRODUCT_REQUIREMENTS.md` (PRD §4.2.3, §4.3.1), and the code (ground truth).
This is the plan; the post-implementation record belongs in `docs/M15_IMPLEMENTATION_REVIEW.md`.

Decision labels used throughout: **EXISTING DOCTRINE** (already enforced in the repo, must not be
reversed), **REQUIRED BY PRD/ROADMAP** (mandated by a cited product/roadmap requirement),
**RECOMMENDATION** (proposed design with rationale), **OWNER DECISION** (a choice needing approval).

---

## 1. Objective

Implement **PO delivery verification / receiving** such that a **verified receipt is the ONLY
mechanism that releases the corresponding PO quantity into inventory and into project costs**.
A verified receipt against an APPROVED PO line:

1. increases the line's `received_quantity`,
2. records a `RECEIVED` stock movement and increases `quantity_on_hand` on the target inventory item,
3. creates a `JobCost` (tagged with the line's M4 `cost_code`) and refreshes `budget_spent`,
4. records audit + notification rows,
5. derives the PO status `PARTIALLY_RECEIVED` or `RECEIVED`.

All of the above commit **atomically in one transaction**. Partial receiving is supported: a
2-of-3-line PO releases only the verified lines. M15 delivers the "commitment → verified
expenditure" half of the PRD §4.2.3 acceptance — *"A delivery without successful verification is
not included in project costing"* — and unblocks Phase 5 vendor-performance tracking.

M15 is Phase-4-independent: evidence is a **manual/physical verification reference** (packing-slip /
delivery-note number + verification note + `verified_by`/`verified_at` + optional `photo_reference`
string). No file upload, no signed GCS URLs, no worker, no queue.

## 2. Current-state baseline (verified against source)

- **Git:** branch `claude-development`, HEAD `e8735d7` (M14, pushed, up to date with origin).
  Working tree carries only doc edits (`AI_CONTEXT.md`, `CURRENT_STATE.md`,
  `M14_IMPLEMENTATION_REVIEW.md`, `SESSION_HANDOFF.md`) + untracked `M14_IMPLEMENTATION_PLAN.md`.
  M15 implementation must leave pre-existing doc edits untouched and must not assume a clean tree.
- **Alembic:** repo head `k4c5d6e7f8a9` (13-revision linear chain); `test_migrations.py`
  `HEAD_REVISION = "k4c5d6e7f8a9"`. **Live dev DB unverified — Docker is down**; do not claim a
  live-DB revision without starting Docker and running `alembic current`.
- **PO model** (`app/models/purchase_order.py`): `PurchaseOrder` (project/vendor FKs, `po_number`
  unique, `status` `POStatus`, `total_amount` denormalized, lifecycle attribution columns);
  `POLine` (description, `quantity` Numeric(12,2), `unit` String(50), `unit_price` Numeric(14,2),
  `cost_code` — reused M4 enum; `line_total` derived on read). **No `received_quantity`, no
  `inventory_item_id`.** `POStatus` = DRAFT/PENDING_APPROVAL/APPROVED/REJECTED/CANCELLED;
  APPROVED/CANCELLED terminal in M14. Docstring + M14 plan §9/§34 reserve additive extension
  (`partially_received`/`received`) for M15.
- **PO routes** (`app/api/v1/purchase_orders.py`): full lifecycle under **project row lock first,
  PO row lock second** (`get_project_for_update` → `_get_po_locked`), audited transitions,
  `_assert_po_writable` (COMPLETED → 400, ARCHIVED → 403 via `assert_project_writable`),
  admin+procurement everywhere, approve/reject/APPROVED-cancel admin-only, S/C 403 on every route.
  M8 idempotency on PO create (`_finish_idempotency_po_create` relationship-safe finalizer) and
  line-add (`idem.finish`).
- **Inventory** (`app/models/inventory.py`, `app/api/v1/inventory.py`,
  `app/services/inventory.py`): `StockMovement` immutable ledger, `MOVEMENT_SIGN[RECEIVED]=+1`,
  `record_movement` locks the **item row** (`with_for_update`), negative-balance 400, M8 idempotency,
  low-stock **crossing-only** notification, `reconcile_project_inventory` ledger check.
  **No `po_line_id` on `stock_movements`.**
- **Job costs** (`app/models/finance.py`, `app/api/v1/finance.py`, `app/services/finance.py`):
  `JobCost(project_id, cost_code, description, amount, incurred_on)`; create/update/delete run under
  the project row lock and call `refresh_budget_spent` (denormalized running total) in-transaction;
  `budget_rollup` recomputes from the ledger on read. M8-protected create. **No `po_line_id`.**
- **Idempotency** (`app/services/idempotency.py`, `app/api/deps.py`): `IdempotencyGuard.finish()`
  refreshes `obj` before serializing — a loaded ORM **relationship** is expired and async
  re-load raises MissingGreenlet (the M14 lesson). See §21 for the M15 response-shape decision.
- **Audit** (`app/middleware/audit.py`): `record_audit()` same transaction; `action` varchar(100);
  no second audit system; `audit_logs`/`daily_site_logs` append-only.
- **Notifications** (`app/services/notifications.py`, `app/models/notification.py`): `type` is a
  constrained `String(50)` app-level enum → **new types need no migration**; recipients resolved
  from roles/assignments; created in the caller's transaction; no duplicates (crossing-only /
  single-fire).
- **Project access** (`app/api/project_access.py`): `get_project_or_404`,
  `get_project_for_update`, `assert_project_writable` (ARCHIVED 403),
  `assert_can_view_project` (archive-404 for non-A/P), `assert_not_client`.
- **Frontend** (`frontend/src/`): `PurchaseOrdersPanel.tsx` (status badges, DRAFT line editor,
  lifecycle actions, `canWrite`/`canApprove`/`frozen` props from `ProjectDetail.tsx`),
  `VendorsPanel.tsx`, `lib/api.ts`, `types/index.ts` (`PurchaseOrderStatus` union,
  `PurchaseOrderLine`, `NotificationType`). Query keys: `["purchase-orders", projectId]`,
  `["inventory", projectId]`, `["job-costs", projectId]`, `["budget", projectId]`,
  `["project", projectId]`.
- **Tests:** 307 passing (300 defs + 7 parametrize expansions in `test_health.py`); concurrency
  doctrine = real separate DB sessions (`concurrent_client` fixture in `test_purchase_orders.py`).

## 3. Source-of-truth documents

| Purpose | Document |
|---|---|
| Bootstrap / navigation | `docs/AI_CONTEXT.md` |
| Current continuation state | `docs/SESSION_HANDOFF.md` |
| Verified current state | `docs/CURRENT_STATE.md` |
| Direction + Phase 5 sequencing | `docs/ROADMAP.md` |
| M14 scope + deferred items | `docs/M14_IMPLEMENTATION_PLAN.md`, `docs/M14_IMPLEMENTATION_REVIEW.md` |
| Product requirements | `docs/PRODUCT_REQUIREMENTS.md` (PRD §4.2.3, §4.3.1) |
| Code + tests | ground truth (any doc conflict resolves in their favor) |

## 4. Business requirements

- **PRD §4.2.3:** every material delivery is verified against its PO (QR **or** photo-verified);
  a delivery is treated as received / admitted to project costs **only after verification**;
  *acceptance:* a delivery without successful verification is not included in project costing.
- **PRD §4.3.1:** every material expense is tagged to a Cost Code and rolls up to project budget
  health in near-real time (M4 `cost_code` on PO lines is the hook).
- **ROADMAP Phase 5 MUST (Delivery verification):** "QR-code scan **or** photo-verified receipt
  against PO lines; verified receipt releases stock into inventory and triggers cost entries."
- **ROADMAP Phase 5 acceptance:** "A PO with 2 of 3 lines verified only releases verified lines to
  stock + costing"; "QR/photo verification is the only path that releases stock (no unverified
  receipt path)."
- **ROADMAP Phase 5 DB changes:** new `deliveries` (+ `delivery_lines` or reuse); `stock_movements`
  add nullable `po_line_id`.
- **M14 plan §34 / AI_CONTEXT §12 / SESSION_HANDOFF §6 (approved deferral):** M15 adds
  `received_quantity`, `stock_movements.po_line_id`, `job_costs` release, additive `POStatus`
  extension, partial-receipt semantics, and a **photo-reference / manual-verify evidence field**
  (NOT full GCS upload — that is Phase 6).

## 5. Explicit non-goals (M15)

- **Real file/photo uploads, GCS signed uploads, presigned URLs, image storage/serving** — Phase 6.
  Evidence is a manual reference + optional `photo_reference` **string** (a URL or external id the
  operator supplies); no upload endpoint, no storage.
- **QR-code infrastructure** — PRD names QR or photo verification; M15 implements the
  manual/physical-verification path (a QR payload string may be stored as the `reference`); a
  camera/QR scan UX and any QR validation is deferred.
- **Multi-location inventory** (warehouse/transit/site), transfers, `location_*` columns — **M16**.
- **7-day low-stock demand forecast** — **M16**; needs a Phase 4 worker. Receipts simply update
  `quantity_on_hand` and may only fire the existing threshold-*crossing* low-stock logic (they
  increase stock, so in practice receipts do not fire low-stock).
- **Reversal / returns / credit movements** — out of scope. A receipt is immutable evidence;
  corrections use the existing general-purpose ledger tools (ADJUSTED / CONSUMED movements, manual
  job-cost edit) — no PO-aware return in M15.
- **Editing or deleting receipts / delivery lines** — receipts are append-only (evidence doctrine).
- **Auto-approve, auto-receive, "receive later"** — no background job; receiving is a synchronous,
  user-initiated POST.
- **Blocking or changing the manual `RECEIVED` movement / manual job-cost endpoints** — those remain
  general-purpose tools for non-PO transactions (see §16/§17 scope note).
- **Changing M4/M5/M6/M8/M10/M13/M14 behavior** — additive only.
- **Any Phase 4 infrastructure** — no Redis, workers, queues, email/push.
- **Hard deletes** — none; all M15 rows follow the soft/append-only lifecycle doctrine.

## 6. User / RBAC matrix

Roles: Admin (A), Procurement Manager (P), Site Supervisor (S), Client (C).

| Operation | Endpoint | A | P | S | C |
|---|---|---|---|---|---|
| Receive a PO | `POST .../purchase-orders/{po_id}/receive` | ✓ | ✓ | 403 | 403 |
| List receipts (delivery history) | `GET .../purchase-orders/{po_id}/deliveries` | ✓ | ✓ | 403 | 403 |
| Get one receipt | `GET .../purchase-orders/{po_id}/deliveries/{delivery_id}` | ✓ | ✓ | 403 | 403 |
| Read PO (now incl. `received_quantity`) | existing `GET` PO routes | ✓ | ✓ | 403 | 403 |

- **EXISTING DOCTRINE:** receiving is a PO write — same role surface as every M14 PO operation
  (admin+procurement); approve/reject remain admin-only and unchanged. Supervisors/clients keep 403
  on every PO route and never receive PO notifications (M4/M5/M14 finance-is-not-a-S/C-surface
  precedent).
- **OWNER DECISION (recommended: admin+procurement):** receiving is **admin+procurement**, not
  procurement-only — it is a PO-scoped write like create/submit, and both roles already manage
  inventory (admin+procurement write inventory in M1) and job costs (admin+procurement in M4).
- **OWNER DECISION (recommended: never):** can a supervisor/client **ever** see receiving data?
  Recommended **no** — no S/C receipt shape, no S/C deliveries read, no PO `received_quantity`
  exposure beyond the A/P PO shape. (Keeps the client portal boundary intact.)

Every receiving endpoint runs `get_project_for_update`/`get_project_or_404` + the project-scoped
IDOR filtering (§24). No `assert_can_view_project` needed (A/P see all projects by role; S/C are
blocked at the role gate).

## 7. PO lifecycle changes

**EXISTING DOCTRINE (unchanged):** no status PATCH; transitions are audited, row-locked
(project → PO), and role-gated; APPROVED/CANCELLED were terminal in M14; header/line edits are
DRAFT-only.

**M15 adds three edges, all via the receive flow (never a direct status endpoint):**

```
APPROVED ──receive (any line, partial/full)──► PARTIALLY_RECEIVED
PARTIALLY_RECEIVED ──receive more (any remaining)──► PARTIALLY_RECEIVED | RECEIVED
APPROVED ──receive (all lines full)──► RECEIVED        (direct when one receipt covers everything)
```

- Status is **derived automatically** inside the receive transaction (§14): any received line with
  remaining > 0 ⇒ PARTIALLY_RECEIVED; every line with `received_quantity == quantity` ⇒ RECEIVED.
- **OWNER DECISION (recommended: yes):** **RECEIVED is terminal.** No further receipts, no header/
  line edits (already frozen by status guards — line edits are DRAFT-only), no cancel.
  **Alternative:** allow post-RECEIVED receipts of surplus (rejected — that is over-receiving).
- **OWNER DECISION (recommended: no extra state):** extend with exactly **`PARTIALLY_RECEIVED`**
  and **`RECEIVED`**. The M14 plan text also floated a `closed` state; a distinct CLOSED adds no
  transition or rule in M15 (RECEIVED already freezes), so it is deferred unless the owner wants an
  accounting-close marker. **If `closed` is wanted**, it must be added in the same migration
  (`ALTER TYPE` additive, no data backfill).
- **OWNER DECISION (recommended: disallow):** **cancelling a partially-received PO is rejected
  (400).** Cancellation keeps its M14 meaning ("the commitment was never honored") and applies only
  to DRAFT/PENDING_APPROVAL/APPROVED-with-zero-received; once any stock/cost has been released,
  cancellation is a reversal problem (out of scope §5). The existing cancel handler must add a guard:
  `PARTIALLY_RECEIVED`/`RECEIVED` → 400 "has received stock; cancellation is not allowed".
- **OWNER DECISION (recommended: same as M14):** receiving is blocked on **COMPLETED** projects
  (400, via the existing `_assert_po_writable`) and **ARCHIVED** (403, via
  `assert_project_writable`). Consistency with the M14 freeze doctrine is preferred over a
  close-out-receiving exception. (Alternative: allow receiving on COMPLETED for close-out — owner
  may approve; it requires a second writability rule.)
- DRAFT/PENDING_APPROVAL/REJECTED/CANCELLED POs cannot receive (400 "only APPROVED or
  PARTIALLY_RECEIVED POs can receive").

## 8. Receiving workflow (business flow)

1. Operator (A/P) opens an APPROVED (or PARTIALLY_RECEIVED) PO on an ACTIVE (or earlier) project.
2. For each line to receive, they select a target **inventory item** (existing project item or one
   created for the project) and enter a positive quantity ≤ remaining.
3. They supply evidence: `reference` (packing-slip / delivery-note / QR payload string), optional
   `note`, optional `photo_reference` (an external URL/id string — no upload).
4. One `POST .../receive` with `Idempotency-Key` commits atomically: receipt header + lines,
   `RECEIVED` stock movements + `quantity_on_hand`, `JobCost` rows + `budget_spent`, audit,
   notification, PO status derivation.
5. UI shows the receipt confirmation, the new per-line `received_quantity`/remaining, and the new
   PO status.

**OWNER DECISION (recommended: one receipt record, one POST):** each receive operation creates
**one `deliveries` row (the receipt/evidence header) + one `delivery_lines` row per received PO
line**. A direct, recordless "receive" (just mutate lines + ledger) is rejected because it would
have no home for evidence/attribution and no way to answer "what was received, by whom, against
which reference, when" — requirements ROADMAP's `deliveries` table already anticipates.

**OWNER DECISION (recommended: yes):** one receipt may contain **multiple PO lines** (a truckload
covering several line items). The schema's `delivery_lines` child table supports this naturally and
the same atomicity rules apply to all lines in the request.

## 9. Data model changes

All money `Numeric(14,2)`, all quantities `Numeric(12,2)`, UUID PKs, Postgres-native enums — the
repo doctrine.

### 9.1 `po_lines` (+2 columns, both nullable-safe additive)

| Column | Type | Notes |
|---|---|---|
| `received_quantity` | `Numeric(12,2)` NOT NULL `DEFAULT 0` | accumulating server-derived total across receipts. **REQUIRED BY ROADMAP/M14-plan** |
| `inventory_item_id` | UUID NULL, FK `inventory_items.id` ON DELETE SET NULL | **OWNER DECISION (recommended: yes, add)** — durable "which item does this line feed"; set on first receipt, immutable thereafter (app-level). Alternative: store the item only on `delivery_lines` and re-validate per receipt. Adding it on the line gives one authoritative linkage and a clean over-receipt/lock story. |

`received_remaining` (== `quantity − received_quantity`) is **derived on read** in the schema/
serializer (like `line_total`) — never stored.

### 9.2 `stock_movements` (+1 column)

| Column | Type | Notes |
|---|---|---|
| `po_line_id` | UUID NULL, FK `po_lines.id` ON DELETE SET NULL | **REQUIRED BY ROADMAP** — provenance on the immutable ledger. Add index `ix_stock_movements_po_line_id` (RECOMMENDATION: reconciliation-by-PO queries). `RECEIVED` movements created by M15 always carry it; manual movements leave it NULL. |

### 9.3 `job_costs` (+1 column) — OWNER DECISION

| Column | Type | Notes |
|---|---|---|
| `po_line_id` | UUID NULL, FK `po_lines.id` ON DELETE SET NULL | **OWNER DECISION (recommended: yes, add)** — provenance for material costs (PO line → JobCost), the foundation for Phase 5 vendor-performance and future material-cost reconciliation. Nullable, additive, no backfill; manual job costs stay NULL. **Alternative:** omit; the JobCost `description` already embeds "PO {po_number}" in the receipt flow, so provenance is recoverable but not structured. |

### 9.4 New table `deliveries` (receipt header)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `project_id` | FK `projects.id` CASCADE NOT NULL | denormalized for scoping/queries (derivable via PO) — **RECOMMENDATION** |
| `purchase_order_id` | FK `purchase_orders.id` CASCADE NOT NULL | |
| `reference` | String(100) NOT NULL | packing-slip / delivery-note / QR payload string — the evidence anchor |
| `note` | Text NULL | verification note |
| `photo_reference` | String(500) NULL | optional external URL/id — **string only, no upload** |
| `verified_by` | FK `users.id` SET NULL NOT NULL | the operator who verified/received |
| `verified_at` | timestamptz NOT NULL | evidence timestamp |
| `created_at` | timestamptz server_default now() | |
| `created_by` | FK `users.id` SET NULL NOT NULL | the acting user (== verified_by in M15) |

Indexes: `(purchase_order_id)`, `(project_id)`, `(verified_at)` (RECOMMENDATION). Append-only —
no update/delete endpoints.

### 9.5 New table `delivery_lines` (receipt line)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `delivery_id` | FK `deliveries.id` CASCADE NOT NULL | |
| `po_line_id` | FK `po_lines.id` RESTRICT NOT NULL | RESTRICT protects receipt evidence (po_lines can only be deleted in DRAFT, so never received) |
| `inventory_item_id` | FK `inventory_items.id` RESTRICT NOT NULL | which item absorbed the stock |
| `quantity_received` | Numeric(12,2) NOT NULL | magnitude; sign is derived (RECEIVED +1) |
| `unit_price` | Numeric(14,2) NOT NULL | **snapshot** of `po_lines.unit_price` at receipt — receipts are immutable financial evidence; later PO edits (which are DRAFT-only anyway) can never alter history |
| `line_total` | Numeric(14,2) NOT NULL | server-derived snapshot = `round(quantity_received × unit_price, 2)` |

Indexes: `(delivery_id)`, `(po_line_id)`, `(inventory_item_id)` (RECOMMENDATION).

### 9.6 `POStatus` enum extension

Add members `PARTIALLY_RECEIVED = "partially_received"` and `RECEIVED = "received"` (member-name
storage, matching M5/M14 enum doctrine). **REQUIRED BY ROADMAP/M14-plan.** See §10 for the
`ALTER TYPE` mechanics and the enum-in-transaction caveat.

### 9.7 Not touched

`inventory_items` (no new columns; `unit_cost` behavior is §17), `vendors`, `purchase_orders`
header (no new columns; status enum extends in place), `notifications` (app-level String enum —
no migration), `projects`, `users`.

## 10. Migration design

**One additive Alembic revision** after `k4c5d6e7f8a9`, planned revision id **`l5d6e7f8a9b0`**
(sequential letter-prefix pattern; the implementer must use the id actually generated by
`alembic revision` and keep `test_migrations.py` `HEAD_REVISION` in lockstep). No existing-table
destructive changes; no data backfill.

Upgrade:
1. `op.execute("ALTER TYPE po_status ADD VALUE IF NOT EXISTS 'PARTIALLY_RECEIVED'")`
2. `op.execute("ALTER TYPE po_status ADD VALUE IF NOT EXISTS 'RECEIVED'")`
   - **Enum-in-transaction caveat (REQUIRED, EXISTING DOCTRINE-derived):** Postgres forbids *using*
     a new enum value in the same transaction that adds it. M15 is a pure schema change (no inserts/
     updates using the new values), so this is satisfied — **do not backfill any row to
     PARTIALLY_RECEIVED/RECEIVED in the migration**.
   - `IF NOT EXISTS` makes replay-after-partial-state safe. The chain test (upgrade → downgrade base
     → upgrade) is fine: M14's downgrade drops the whole `po_status` type, so the replay recreates it
     with 5 values and M15 re-adds the 2.
3. `po_lines`: `add_column received_quantity Numeric(12,2) NOT NULL server_default '0'`;
   `add_column inventory_item_id UUID NULL` + FK `inventory_items.id` ON DELETE SET NULL (if §9.1
   OWNER DECISION = yes).
4. `stock_movements`: `add_column po_line_id UUID NULL` + FK `po_lines.id` ON DELETE SET NULL;
   index `ix_stock_movements_po_line_id`.
5. `job_costs`: `add_column po_line_id UUID NULL` + FK `po_lines.id` ON DELETE SET NULL (if §9.3
   OWNER DECISION = yes).
6. Create `deliveries` + `delivery_lines` (constraints/indexes per §9.4/§9.5). No new native enum
   type is created, so the M5/M14 "create type with checkfirst before create_table" pitfall does
   not apply to the new tables.

Downgrade (non-destructive to pre-existing data):
- drop `delivery_lines`, `deliveries`; drop the 3 (or 2) added columns + FKs + indexes.
- **`po_status` enum values cannot be `DROP`ped** (Postgres has no `ALTER TYPE ... DROP VALUE`
  until very recent versions and it is not used in this repo). Document: a downgrade leaves the two
  new enum members present-but-unused in the type; the **chain test tolerates this** because the
  full downgrade to base drops the entire enum via the M14 downgrade. If a mid-chain downgrade of
  only `l5d6e7f8a9b0` is ever needed, residual enum members are harmless (no column references them).

`test_migrations.py`: update `HEAD_REVISION` to `l5d6e7f8a9b0`; assert `deliveries`/
`delivery_lines` tables exist after upgrade and are dropped on downgrade; assert
`po_lines.received_quantity` and `stock_movements.po_line_id` columns exist/are dropped; assert the
enum contains the two new values after upgrade.

## 11. API design

All under the existing PO router prefix (`/projects/{project_id}/purchase-orders`) so they reuse
`get_project_for_update`, `_get_po_locked`, `_assert_po_writable`, and the IDOR-filtered loaders
(no new router module — **RECOMMENDATION**; keeps lock order and RBAC in one file).

| Method | Path | RBAC | Notes |
|---|---|---|---|
| POST | `/{po_id}/receive` | A, P | **idempotency-protected (M8)**; creates receipt + stock + costs; returns `DeliveryRead` (201) |
| GET | `/{po_id}/deliveries` | A, P | receipt history, newest first |
| GET | `/{po_id}/deliveries/{delivery_id}` | A, P | single receipt with its lines |

No PATCH/DELETE on deliveries (append-only evidence). No changes to existing PO/lifecycle routes
except the cancel guard (§7).

Handlers:
- `receive_purchase_order`: `idem.replay` short-circuit → `get_project_for_update` →
  `_assert_po_writable(project)` → `_get_po_locked(db, project_id, po_id)` → validate status ∈
  {APPROVED, PARTIALLY_RECEIVED} → validate payload (§13/§14) → load + **lock each target
  `inventory_item` row (`with_for_update`)** → apply receipt → derive status → audit → notify →
  `idem.finish(...)` → `db.commit()` → re-read + return.
- The whole receive is a single request-scoped transaction.

## 12. Request / response schemas

`app/schemas/delivery.py` (new):
- `DeliveryLineCreate` (from `POLineCreate` conventions): `po_line_id: UUID`, `quantity: float
  Field(gt=0)`, `inventory_item_id: UUID`. Money/amounts are NEVER client-supplied.
- `DeliveryCreate`: `reference: str Field(min_length=1, max_length=100)`, `note: str | None
  (max 2000)`, `photo_reference: str | None Field(max_length=500)`, `lines: list[DeliveryLineCreate]
  (min_length=1)`.
- `DeliveryLineRead`: id, delivery_id, po_line_id, inventory_item_id, quantity_received,
  unit_price, line_total, plus transient `description`/`unit` attached from the PO line on read
  (setattr doctrine). **Owns its fields independently of the ORM relationship** for idempotency
  safety (§21).
- `DeliveryRead`: **mapped columns only + transient `line_count`/`po_status_after`** — see §21.
  Fields: id, project_id, purchase_order_id, reference, note, photo_reference, verified_by,
  verified_at, created_by, created_at, line_count, po_status_after.

`app/schemas/purchase_order.py` (modified):
- `POLineRead`: add `received_quantity: float` and `received_remaining: float` (derived on read) and
  `inventory_item_id: UUID | None`. (A/P-only shape — no S/C PO shape exists.)
- `PurchaseOrderRead`: unchanged fields; status enum now includes the two new members.

## 13. Validation / error semantics

Uniform `{detail, errors}` FastAPI shape (existing global handlers):

| Status | Meaning |
|---|---|
| 400 | receive on non-{APPROVED, PARTIALLY_RECEIVED} PO; over-receiving a line (`received_quantity + qty > quantity`); line with zero remaining; `inventory_item_id` of a different project; item/PO-line **unit mismatch**; item already linked to another PO line (if §9.1 linkage enforced); cancel of PARTIALLY_RECEIVED/RECEIVED; COMPLETED-project freeze (existing) |
| 403 | S/C on any receiving route; ARCHIVED-project write (existing `assert_project_writable`) |
| 404 | PO/line/inventory item not found; cross-project PO/line/item id (IDOR — never 403) |
| 409 | Idempotency-Key reuse with a different body / concurrent same-key / expired key (M8) |
| 422 | schema violations: `quantity <= 0`, empty `lines`, missing `reference`, malformed UUIDs, `photo_reference` too long |
| 401 | missing/invalid bearer token (dependency) |

Validation rules:
- **Unit consistency (RECOMMENDATION):** the target `inventory_item.unit` must equal the PO line's
  `unit` (both String(50) vocabularies) → 400 on mismatch. Prevents "50 bags → 50 kg" drift.
- **Item linkage (if §9.1 = yes):** `po_lines.inventory_item_id` is set on first receipt and must
  match the item on every later receipt of the same line (400 on divergence).
- **Item project scope:** `inventory_item_id` must belong to `project_id` (404 otherwise).
- **No-op receipts:** every line in the payload must receive `> 0` and `<= remaining` (400).
- Money/quantities: the client supplies only positive quantities + references; signs, `line_total`,
  job-cost amounts, and statuses are **server-derived** (doctrine).

## 14. Partial receiving rules

- A PO line is independently receivable in **any number of receipts**, each with a positive
  quantity. `received_quantity` accumulates; `received_remaining = quantity − received_quantity`.
- A receipt may cover **one or many lines**; each is applied atomically or not at all (§22).
- Status derivation after a receipt (pure function in the service layer):
  - every line has `received_quantity >= quantity` ⇒ `RECEIVED`;
  - otherwise (at least one line received, at least one line with remaining > 0) ⇒
    `PARTIALLY_RECEIVED`.
  - Receiving is allowed from {APPROVED, PARTIALLY_RECEIVED} only; RECEIVED is terminal (§7).
- A receipt on a line whose remaining is already 0 is a no-op → 400 (prevents zero-value receipts).
- **RECOMMENDATION:** quantities may be arbitrary Decimals > 0 up to remaining (e.g. a line of 100
  may be received 40 then 60; or 25/25/50). No requirement that a receipt "completes" a line.

## 15. Over-receiving prevention

- **EXISTING DOCTRINE (no DB CHECK constraints):** enforcement is app-level inside the locked
  transaction: after locking the project, the PO, and the target items, compute
  `new_received = line.received_quantity + payload.quantity`; reject with 400 if
  `new_received > line.quantity`.
- **Concurrency:** the project row lock serializes all writes to a project's POs (M14 doctrine), so
  two concurrent receipts against the same PO line cannot both read the same stale
  `received_quantity` — the second transaction runs after the first commits and sees the updated
  total. Test-pinned with real separate sessions (§26: concurrent receives, concurrent same-line).
- A DB-level CHECK would be a stronger backstop but is rejected to preserve the "no DB CHECK
  constraints" doctrine.

## 16. Inventory integration

- Each `delivery_line` produces one `StockMovement`:
  `movement_type=RECEIVED`, `quantity=quantity_received`, `po_line_id=<po line>`,
  `recorded_by=<actor>`, `note="Received against PO {po_number}"`, and increments the item's
  `quantity_on_hand` — all inside the receipt transaction.
- The item row is locked (`SELECT ... FOR UPDATE`) before the balance update — the M1 pattern.
- **Scope note (important):** the "only mechanism" invariant (§1, ROADMAP acceptance) applies to
  **PO quantities** — the PO line's quantity cannot enter inventory or costing except through a
  verified receipt. The **existing** general-purpose `POST /inventory/{item}/movements` (RECEIVED/
  CONSUMED/ADJUSTED/TRANSFERRED) and `POST /job-costs` remain available for **non-PO** transactions
  (manual adjustments, site purchases outside a PO, opening balances). **RECOMMENDATION:** do not
  block manual RECEIVED movements on items that happen to be linked to PO lines — that would break
  M1 semantics and legitimate non-PO stock. If the owner wants PO-linked items to reject manual
  RECEIVED, that is a separate rule (OWNER DECISION; not recommended).
- Receipts only **increase** stock, so the M13 low-stock **crossing** hook (old > threshold ≥ new)
  cannot fire on a receipt (balance goes up). No special handling needed, but the receipt code must
  not call `notify_low_stock`.

## 17. Job-cost integration

- Each `delivery_line` produces one `JobCost`:
  `project_id`, `cost_code = po_line.cost_code` (M4 enum), `description =
  "PO {po_number} — {po_line.description}"` (+ `po_line_id` if §9.3 approved),
  `amount = round(quantity_received × unit_price_snapshot, 2)` (server-derived; the delivery_line's
  stored `line_total`), `incurred_on = verified_at.date()`.
- `refresh_budget_spent(db, project)` runs in the same transaction → `budget_spent` and the M3
  budget-health signal grow with verified material spend (correct, PRD §4.3.1 near-real-time).
- **OWNER DECISION (recommended: set-if-unset):** `InventoryItem.unit_cost` — on the first receipt
  into an item whose `unit_cost` is NULL, set it to the PO line `unit_price` (server-derived best
  known cost), audited. Do **not** overwrite a manually-entered `unit_cost`; do not compute a
  weighted average in M15 (a per-location cost model belongs to M16). Alternative: never touch
  `unit_cost` (keep it a purely manual field).

## 18. Budget integration

- `budget_spent` is derived from `SUM(job_costs)` and refreshed in-transaction (existing M4
  service — reuse verbatim). Receipts add job costs, so budget spending rises at the verified
  moment. No changes to `budget_rollup`, M5 invoicing, or health computation.

## 19. Audit requirements

- **EXISTING DOCTRINE:** `record_audit()` in the same transaction; no second audit system.
- New action **`po_receive`** (on `deliveries`, `record_id=delivery.id`) recording: po_id, po_number,
  reference, verified_by, line_count, received-total, new status (old→new), total received amount.
  (Single event per receipt, mirroring `po_submit`/`po_approve`.)
- `po_cancel` guard: when cancellation is rejected for PARTIALLY_RECEIVED/RECEIVED, nothing is
  audited (the request fails before mutation — consistent with M14 illegal-transition behavior).
- `stock_movements`/`job_costs`/`delivery_lines` are ledger/evidence rows; they are not additionally
  audited per row (the `po_receive` event + the immutable ledger ARE the trail — M1/M4 doctrine).
  If the owner wants per-movement audit, that is an OWNER DECISION (not recommended; duplicates the
  ledger).

## 20. Notification requirements

- **EXISTING DOCTRINE (M13):** new `NotificationType` value needs **no migration** (String(50));
  created in the caller's transaction; minimal bodies; single-fire (a receipt is one event; M8
  replay cannot re-run it).
- New type: **`po_received`** (frontend union `"po_received"` in `types/index.ts`).
- **OWNER DECISION (recommended):** recipients = **PO creator (if active) + all active admins** —
  the M14 approve/reject pattern. Body distinguishes partial vs full ("PO {n} partially received
  (2 of 3 lines)" / "PO {n} fully received"), link `/projects/{project_id}`. Alternative: also
  notify all active procurement managers (global role, like low-stock) — owner choice; not
  recommended because procurement is typically the receiving actor.
- **OWNER DECISION (recommended: single type):** one `po_received` type whose body/text carries
  partial/full. Alternative: separate `po_partially_received`/`po_received` types (more precise
  filters, slightly more surface). Recommended single type keeps the union small.
- Supervisors/clients never receive it (they see no POs).

## 21. Idempotency behavior

- **EXISTING DOCTRINE (M8):** `POST .../receive` is idempotency-protected. A retry with the same
  key + body replays the stored receipt verbatim (same delivery id, ledger/stock/budget untouched);
  same key + different body → 409; failed attempt frees the key; concurrent same-key → exactly one
  receipt + one claim row (the `(actor_id, operation, idempotency_key)` unique index).
- **M14 finalizer issue — resolution (RECOMMENDATION, aligned with the plan directive):** M14's
  `_finish_idempotency_po_create` existed because `IdempotencyGuard.finish()`'s internal
  `db.refresh(obj)` expires loaded ORM **relationships** (async re-load → MissingGreenlet), and the
  PO response carries the `lines` relationship. **M15 avoids duplicating that workaround:**
  - The receive response is **`DeliveryRead` with mapped scalar columns only** (+ transient
    `line_count`/`po_status_after` attached via `setattr`). It does **not** serialize
    `delivery.lines` through an ORM relationship, so the plain `idem.finish(db, ..., obj=delivery,
    response_model=DeliveryRead)` path is safe (Session.refresh only reloads mapped attributes;
    the transient scalars are re-set after `idem.finish`/before return if the response path needs
    them — see below).
  - The handler calls `idem.finish(...)` **before** `db.commit()`; after commit it re-reads the
    delivery + its lines in a fresh query and attaches line-level details only for the
    **non-replayed** return value. Detail is always available via `GET .../deliveries/{id}`.
  - `GET` list/detail endpoints are not idempotency-protected (M8 doctrine: reads).
- If the implementer prefers returning full line detail in the receive response, they must either
  use the M14-style named-columns finalizer (explicitly discouraged here) or attach `lines` as a
  transient attr *after* finalize — not acceptable (finalize serializes before commit). **The
  documented approach (flat `DeliveryRead`) is the approved one.**

## 22. Transaction / atomicity guarantees

One transaction per receive (single request-scoped session, existing `get_db`):
- Acquire locks in order (§23), perform every guard (status, remaining, over-receipt, item scope,
  unit match, linkage), insert `deliveries` + `delivery_lines`, insert `StockMovement`s and update
  `quantity_on_hand` on each item, insert `JobCost`s and `refresh_budget_spent`, derive + set PO
  status, `record_audit` (`po_receive`), `create_notifications` (`po_received`), `idem.finish`, then
  `db.commit()`.
- **Any failure — an exception anywhere in the handler — rolls back ALL of the above** (data +
  stock + costs + budget + audit + notification + idempotency claim) because they share the
  transaction. A failed request leaves no partial receipt and leaves the `Idempotency-Key` free for
  a safe retry (M8 semantics). Test-pinned in §26 (rollback tests).

## 23. Locking / concurrency strategy

- **EXISTING DOCTRINE:** acquire the **project row lock first** (`get_project_for_update`), then
  the **PO row lock** (`_get_po_locked`), then the **inventory item row locks**
  (`SELECT ... FOR UPDATE` per target item). **Never reverse the order**; never lock a second
  project or a second PO in the same transaction; never lock an item without first holding the
  project lock. Lock graphs stay acyclic → no deadlock reachable.
- Because every receipt locks its own project row, two concurrent receipts in the same project
  (even against **different POs**) serialize at the project level — correct and consistent with M14.
  Concurrent receipts against the **same PO line** are therefore serialized end-to-end:
  `received_quantity` can never be read stale, so over-receiving is impossible under concurrency.
- Vendor rows are untouched by receiving (no lock needed).
- Reads (`GET` deliveries) take no locks (consistent with PO reads).

## 24. Security / IDOR / data-leakage analysis

- **Role gating:** every new endpoint `require_role(ADMIN, PROCUREMENT_MANAGER)`. S/C get 403; no
  S/C receipt/PO shape exists (M6/M14 boundary preserved).
- **IDOR:** all PO/line/item lookups filter by `project_id` AND the child id → cross-project
  PO/line/`inventory_item_id` returns 404 (never 403/leak). The item lookup adds
  `InventoryItem.id == item_id AND InventoryItem.project_id == project_id`.
- **Archived:** `assert_project_writable` → 403 for A/P writes; S/C never reach the routes.
- **Money:** amounts are server-derived from stored PO prices; the client never supplies money; the
  `line_total`/job-cost/`unit_cost` values are computed in-service.
- **Evidence fields:** `reference`/`photo_reference` are arbitrary strings — validate length only;
  never render them as trusted HTML (React auto-escaping is in place); a URL in `photo_reference`
  is inert until Phase 6 serving exists.
- **Notifications:** recipient resolution reuses existing role data; bodies carry only PO numbers +
  line counts (no money beyond what A/P see).
- **Rate limiting:** no new public endpoints (all bearer-gated), consistent with existing traffic.
- **Audit immutability:** deliveries are append-only; nothing new is UPDATE/DELETE-able.

## 25. Frontend UX

- `types/index.ts`: extend `PurchaseOrderStatus` with `"partially_received" | "received"`;
  `PurchaseOrderLine` += `received_quantity: number`, `received_remaining: number`,
  `inventory_item_id: string | null`; new `Delivery`, `DeliveryLine`, `DeliveryCreateInput`
  (`{reference, note?, photo_reference?, lines: [{po_line_id, quantity, inventory_item_id}]}`)
  types; `NotificationType` += `"po_received"`.
- `lib/api.ts`: `receivePurchaseOrder(projectId, poId, input)` (with `Idempotency-Key` —
  generate per logical operation, reuse on retry per the M8 frontend-gap note), `listDeliveries(projectId, poId)`, `getDelivery(projectId, poId, deliveryId)`.
- `components/PurchaseOrdersPanel.tsx`:
  - `poStatusBadge`: add `partially_received` (amber accent) and `received` (green "Received").
  - Per-line display: `received_quantity / quantity` + `received_remaining` when `> 0`.
  - "Receive stock" action when `canWrite && !frozen && (status === "approved" ||
    status === "partially_received")`: a form listing each receivable line (remaining > 0) with a
    quantity input (default = remaining), an inventory-item picker (project items from
    `["inventory", projectId]`), plus `reference` (required), optional `note` and `photo_reference`.
  - Submit → invalidate `["purchase-orders", projectId]`, `["inventory", projectId]`,
    `["job-costs", projectId]`, `["budget", projectId]`, `["project", projectId]`.
  - Receipt history: expandable list from `listDeliveries` (reference, verified_by, verified_at,
    line count).
- `pages/ProjectDetail.tsx`: pass no new props (receive is `canWrite`); the query invalidation above
  covers the panels. No client/supervisor surfaces.
- Keep the existing loading/error/empty conventions (Loader2, `getErrorMessage`, empty-state copy).

## 26. Test strategy

New `backend/tests/test_receiving.py` (real ASGI client + real Postgres; concurrency via
**real separate DB sessions** — the `concurrent_client` per-request-session fixture pattern from
`test_purchase_orders.py`, never mocked locks). Coverage:

- **RBAC matrix:** A/P can receive + list; S/C 403 on all three new endpoints; approve/reject
  unchanged (admin-only).
- **IDOR/cross-project:** receive with another project's `po_line_id`/`inventory_item_id` → 404; PO
  of another project → 404.
- **Partial receiving:** 2-of-3-line PO releases only verified lines (stock + costs for 2); status
  PARTIALLY_RECEIVED; unverified line untouched.
- **Full receiving:** all lines in one receipt → RECEIVED; `quantity_on_hand` + `budget_spent` +
  job costs match exactly.
- **Multiple receipts:** 40 + 60 on a 100 line → line fully received on the second, status RECEIVED,
  ledger shows 2 movements, 2 job costs.
- **Exact boundary:** receive exactly `remaining` succeeds; a further receipt of any positive amount
  → 400 (no-op/over).
- **Over-receiving:** `quantity > remaining` → 400; `quantity <= 0` → 422.
- **Invalid PO states:** receive on DRAFT/PENDING_APPROVAL/REJECTED/CANCELLED → 400; receive on
  RECEIVED → 400; cancel of PARTIALLY_RECEIVED/RECEIVED → 400; submit/approve/reject/cancel flows
  unaffected.
- **Invalid project states:** COMPLETED → 400; ARCHIVED → 403; receipt on DRAFT/PLANNING/ON_HOLD/
  ACTIVE allowed.
- **Unit mismatch** (PO line unit ≠ item unit) → 400; **item-linkage divergence** (second receipt
  targets a different item) → 400.
- **Concurrency (real separate sessions):** two concurrent receipts on the **same PO line** →
  serialized, `received_quantity` = sum, no over-receipt (or the loser 400s when total would exceed);
  two concurrent receipts on **different PO lines** of the same PO → both commit, correct status.
- **Idempotency:** replay same key + body → same delivery id, no second receipt/stock/cost/audit/
  notification; same key + different body → 409; failed attempt (e.g. over-receive) frees the key
  for a safe retry; concurrent same-key → one receipt + one claim row.
- **Rollback:** a forced mid-handler failure (e.g. over-receipt on the second line) leaves **no**
  deliveries/delivery_lines/stock movements/job costs/budget change/audit/notification rows (assert
  via DB).
- **Notifications:** `po_received` → creator + admins, none to S/C; atomic with the receipt
  (rolled-back receipt → no notification).
- **Audit:** `po_receive` row present with old→new status + reference; cancel-of-partial-received
  audited nothing.
- **Inventory/job-cost integrity:** `reconcile_project_inventory` shows ledger==on-hand after
  receipts; `budget_spent == SUM(job_costs)` after receipts.

`tests/test_notifications.py`: +~3 (partial, full, S/C absence).
`tests/test_migrations.py`: HEAD → `l5d6e7f8a9b0`; new tables/columns/enum values asserted
up/down/replay.

**Regression (MUST, unchanged):** full M1–M14 suite (307 → ~345 expected) green; frontend
`npm run build` + `npm run lint`; ruff/mypy/oxlint baseline-delta gates pass (zero new findings);
`git diff --check` clean.

## 27. Regression strategy

- Additive-only changes; no modifications to M4/M5/M6/M8/M10/M13/M14 route logic except the single
  cancel guard (§7) and the additive PO/PO-line schemas.
- Existing suites that pin PO behavior (`test_purchase_orders.py`, `test_vendors.py`,
  `test_notifications.py`) must stay green; the PO status badge/`PurchaseOrderStatus` union change is
  the one deliberate shape change (additive).
- The project row-lock/PO row-lock ordering is preserved; new item locks are acquired **after** the
  PO lock (never reordered).
- `test_client_portal.py` (17) and `test_invoicing.py` (31) must be untouched and green (receiving
  touches no client or invoice surface).

## 28. Migration-chain strategy

- One new revision `l5d6e7f8a9b0` appended to the single linear chain; `test_migrations.py`
  upgrade→downgrade→replay must pass (enum caveat handled in §10). Additive; downgrade drops only
  M15 objects/columns; no existing data touched.

## 29. Live smoke-test strategy

Dev-only harness (M14 precedent: `backend/scripts/m15_smoke.py` + `m15_smoke_prep.py`) against a
scratch Postgres + uvicorn, or manual via the SPA against `docker compose up -d postgres`:
1. A/P: create vendor + PO (2–3 lines, mixed cost codes) on an ACTIVE project → submit → admin
   approve.
2. Receive 1 line partially with reference → PO PARTIALLY_RECEIVED; inventory shows the item's
   on-hand increased with a RECEIVED movement carrying `po_line_id`; a matching `JobCost` exists;
   `budget_spent` grew; notification in the creator's bell; audit shows `po_receive`.
3. Receive the remaining lines (incl. exact boundary) → PO RECEIVED; further receive → 400.
4. Try over-receiving → 400; a second item/unit-mismatch → 400; cross-project item → 404.
5. S/C login → 403 on every receiving route; client portal unchanged.
6. COMPLETED project → receive 400; ARCHIVED → 403.
7. Cancel an APPROVED (zero received) PO (admin) still works; cancel of PARTIALLY_RECEIVED → 400.
8. Re-issue the same `Idempotency-Key` with the same body → identical receipt replayed, no dupes.

## 30. Rollback strategy

- **Up:** apply `l5d6e7f8a9b0` (additive).
- **Rollback:** revert code (models/schemas/services/routes/hooks/frontend) then
  `alembic downgrade l5d6e7f8a9b0` (or `-1`) — drops the two new tables + the added columns; the
  two new enum members remain in `po_status` (unused; harmless; no column references them).
- No data backfill in either direction; M14 tables/data untouched.

## 31. Documentation updates

- `docs/M15_IMPLEMENTATION_REVIEW.md` (post-implementation canonical record).
- `docs/CURRENT_STATE.md`, `docs/ROADMAP.md` (Phase 5 status), `docs/SESSION_NOTES.md`.
- `docs/AI_CONTEXT.md` + `docs/SESSION_HANDOFF.md` regenerated at handoff (new HEAD, test count,
  Alembic head `l5d6e7f8a9b0`, M15 done, M16 next).
- Do not modify prior plan/review docs.

## 32. Expected files

**Backend new:**
- `backend/alembic/versions/l5d6e7f8a9b0_m15_receiving_deliveries.py`
- `backend/app/models/delivery.py` (Delivery, DeliveryLine)
- `backend/app/schemas/delivery.py`
- `backend/app/services/receiving.py` (pure domain math: remaining, status derivation,
  over-receipt guard, amount derivation — mirror `purchase_orders.py` style)
- `backend/tests/test_receiving.py`
- `backend/scripts/m15_smoke.py`, `backend/scripts/m15_smoke_prep.py` (dev-only smoke harness)

**Backend modified:**
- `backend/app/models/purchase_order.py` (POStatus members; POLine.received_quantity/
  inventory_item_id)
- `backend/app/models/inventory.py` (StockMovement.po_line_id)
- `backend/app/models/finance.py` (JobCost.po_line_id — if §9.3 approved)
- `backend/app/models/__init__.py` (exports Delivery, DeliveryLine)
- `backend/app/schemas/purchase_order.py` (POLineRead received fields)
- `backend/app/api/v1/purchase_orders.py` (receive + deliveries endpoints; cancel guard)
- `backend/app/services/notifications.py` (+ notify_po_received)
- `backend/app/models/notification.py` (+ NotificationType.PO_RECEIVED)
- `backend/tests/test_migrations.py` (HEAD + assertions)
- `backend/tests/test_notifications.py` (+ receiving tests)

**Frontend modified:**
- `frontend/src/types/index.ts`, `frontend/src/lib/api.ts`,
  `frontend/src/components/PurchaseOrdersPanel.tsx`
  (`pages/ProjectDetail.tsx` only if a new prop/invalidation is needed)

**Docs:** this plan + the §31 updates.

## 33. Owner decisions requiring approval

1. **Receipt entity:** one `deliveries`/`delivery_lines` record per receive POST (recommended) vs a
   recordless direct receive.
2. **Inventory linkage:** add `po_lines.inventory_item_id` set on first receipt (recommended) vs
   item stored only on `delivery_lines`.
3. **Multi-line receipts:** one receipt may contain multiple PO lines (recommended).
4. **Evidence fields:** `reference` (required, may carry a QR payload string) + `note` +
   `photo_reference` string (optional) + `verified_by`/`verified_at` (recommended).
5. **PO status names:** add exactly `PARTIALLY_RECEIVED` + `RECEIVED` (recommended); optionally also
   `CLOSED`.
6. **RECEIVED terminal:** yes (recommended).
7. **Partial semantics:** arbitrary positive quantities ≤ remaining per line (recommended).
8. **Cancellation after partial receipt:** disallow (recommended).
9. **Job-cost provenance:** add `job_costs.po_line_id` (recommended).
10. **`InventoryItem.unit_cost`:** set on first receipt when currently NULL, never overwrite
    manual (recommended).
11. **Notification recipients:** PO creator + active admins (recommended).
12. **Notification types:** single `po_received` (recommended) vs separate partial/full types.
13. **Receiving RBAC:** admin + procurement (recommended).
14. **S/C visibility of receiving data:** none (recommended).
15. **Receiving on COMPLETED projects:** blocked (recommended, M14 consistency) vs allowed for
    close-out.
16. **Reversal/returns:** out of scope for M15 (recommended).
17. **Manual RECEIVED on PO-linked items:** remain allowed as general-purpose ledger tools
    (recommended) vs blocked.

## 34. Implementation sequence

1. Migration `l5d6e7f8a9b0` + `test_migrations.py` HEAD/assertions.
2. Models (`delivery.py`; extend `purchase_order.py`/`inventory.py`/`finance.py`; `models/__init__`).
3. Schemas (`delivery.py`; extend `purchase_order.py`).
4. Service `services/receiving.py` (pure math + status derivation).
5. Routes: receive + deliveries list/detail in `api/v1/purchase_orders.py`; cancel guard.
6. Notifications: type + `notify_po_received` hook.
7. Tests: `test_receiving.py`, `test_notifications.py` extensions.
8. Frontend: types → api.ts → PurchaseOrdersPanel (badges, received/remaining, receive form,
   deliveries history).
9. Full suite + quality gates + migration chain.
10. Docs + smoke + review.

## 35. Acceptance criteria

- A verified receipt is the **only** way a PO line's quantity enters inventory and costing;
  an unverified PO has zero effect on `stock_movements`/`quantity_on_hand`/`job_costs`/`budget_spent`.
- A 2-of-3-line PO releases exactly the 2 verified lines (stock + costs); status PARTIALLY_RECEIVED.
- Fully-received PO → RECEIVED; further receives and cancel → 400; over-receiving → 400;
  zero/negative quantities → 422.
- Inventory item on-hand equals the ledger (reconciliation) and increases by exactly the verified
  quantities; `StockMovement.po_line_id` populated on receipt movements.
- `budget_spent == SUM(job_costs)` holds after receipts; each material `JobCost` carries the line's
  cost code.
- Everything (receipt + stock + costs + budget + audit + notification + idempotency claim) commits
  atomically or rolls back fully.
- RBAC/IDOR: S/C 403 on all new endpoints and no notifications; cross-project ids 404; COMPLETED
  400 / ARCHIVED 403.
- Idempotency: replay verbatim, different-body 409, failed attempt frees the key.
- Full M1–M14 regression + migration chain + frontend build/lint + baseline-delta gates green.
- No Phase 4 infrastructure, no GCS upload, no worker/queue introduced.

## 36. Self-review checklist

- **RBAC/IDOR:** every new endpoint A/P-gated; S/C no shape/notifications; all lookups
  project-scoped → cross-project 404. ✓
- **State-machine gaps:** status changes only through the receive flow or existing transitions;
  RECEIVED terminal; cancel guard for PARTIALLY_RECEIVED/RECEIVED; no status PATCH. ✓
- **Over-receiving/concurrency:** project→PO→item locks; over-receipt checked under the locks;
  real-session concurrency tests. ✓
- **Money correctness:** Decimal ROUND_HALF_UP; amounts derived from stored PO prices; delivery
  line `unit_price`/`line_total` snapshotted; client never supplies money. ✓
- **Atomicity:** single transaction for all effects; rollback tests assert no partial state. ✓
- **Idempotency:** normal `idem.finish()` path with a relationship-free `DeliveryRead` — M14
  workaround not duplicated. ✓
- **Ledger/budget invariants:** `quantity_on_hand == Σ ledger`, `budget_spent == Σ job_costs`
  post-receipt (reconciliation + budget tests). ✓
- **Doctrine preservation:** lock ordering, audit-in-txn, notification-in-txn, append-only receipts,
  no DB CHECKs, additive migration, no Phase 4 infra. ✓
- **Scope control:** M16 (locations/forecast) and Phase 6 (uploads/offline) explicitly untouched. ✓
- **M14 behavior:** only the additive cancel guard and PO-read shape change; PO/vendor suites stay
  green. ✓

**Recommendation:** proceed with M15 — verified receiving with partial/full receipts, ledgered stock
release, job-cost release, status derivation, evidence-by-reference (no uploads), after the §33
owner decisions are approved.

---

## Appendix A — Explicit M15 vs M16 vs Phase 6 split

| Area | M15 (this plan) | M16 | Phase 6 |
|---|---|---|---|
| Receiving / verified delivery | ✓ full | — | — |
| Partial / full receipt | ✓ | — | — |
| Inventory release (`RECEIVED`, `po_line_id`) | ✓ | — | — |
| Job-cost + budget release | ✓ | — | — |
| PO status progression + audit + notification | ✓ | — | — |
| Multi-location (warehouse/transit/site), transfers | — | ✓ | — |
| 7-day demand forecast (worker) | — | ✓ | — |
| Vendor performance tracking | (seeds via delivery data only) | ✓ | — |
| Real photo/file uploads, GCS signed URLs | — | — | ✓ |
| Offline sync / PWA | — | — | ✓ |
