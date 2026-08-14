# ICE Platform — Session Handoff

Current working-session handoff. **Not** a historical document — describes the
**currently verified** repository state so a completely fresh OpenCode session
can continue without this conversation's context. Facts in this file were
re-verified on Aug 14, 2026; trust code/tests over any stale wording here.

## 1. Handoff Status

- **Date:** Aug 14, 2026 (session).
- **Branch:** `claude-development`; **HEAD:** `e8735d7` (feat: add vendors and
  purchase orders — M14), **up to date with origin/claude-development**.
- **M14 (`e8735d7`) is committed AND pushed.** M13 (`3315957`) and the M6
  close-out (`7795890`) are committed and pushed as well.
- **Working tree (uncommitted):**
  - Docs housekeeping from the prior session: `docs/AI_CONTEXT.md`,
    `docs/SESSION_HANDOFF.md`, `docs/CURRENT_STATE.md` (test-count fix),
    `docs/M14_IMPLEMENTATION_REVIEW.md` (status update); untracked canonical
    plans `docs/M14_IMPLEMENTATION_PLAN.md` and
    `docs/M15_IMPLEMENTATION_PLAN.md`.
  - **M15 step-1 implementation (in progress, uncommitted):** migration
    `backend/alembic/versions/l5d6e7f8a9b0_m15_receiving_deliveries.py`,
    `backend/app/models/delivery.py`, `backend/app/schemas/delivery.py`,
    modified `models/purchase_order.py`/`inventory.py`/`finance.py`/
    `__init__.py`, `schemas/purchase_order.py`, and
    `tests/test_migrations.py` (HEAD → `l5d6e7f8a9b0`).
  - Receiving routes/service/notifications/frontend/smoke tests are **not yet
    implemented**.
- **Database:** repo Alembic head **`l5d6e7f8a9b0`** (M15) and the **live dev
  DB is verified at the same revision** (Docker up, `ice-platform-*` healthy;
  migrated `j8e9f0a1b2c3 → k4c5d6e7f8a9 → l5d6e7f8a9b0` via an image rebuild).

## 2. Current Project State

- **Completed milestones (all committed + pushed):** Phase 1, Phase 2, M1–M14,
  P4.1 (one-line list in `docs/AI_CONTEXT.md` §3). M14 (`e8735d7`) is the
  newest milestone commit. **M15 is IN PROGRESS** (step 1 of the approved plan
  landed, uncommitted).
- **Alembic repo head = `l5d6e7f8a9b0`** (M15 `deliveries`/`delivery_lines` +
  `po_status` extension, `po_lines.received_quantity`/`inventory_item_id`,
  `stock_movements.po_line_id`, `job_costs.po_line_id`); the migration chain is
  chain-tested through this revision. **Live dev DB verified at the same
  revision.**
- **Backend tests:** **307 passing** (verified Aug 14, 2026), incl. 13 M14
  vendor, 32 M14 purchase-order, 18 notification, 21 M12 scheduling, 20 M11
  Google, 17 M6 client-portal, and the migration-chain test through
  `l5d6e7f8a9b0`.
- **Frontend:** `npm run build` passes; `npm run lint` passes with 1
  pre-existing warning (`auth-context.tsx` Fast Refresh). Frontend untouched by
  M15 step 1.
- **Quality gates:** ruff 2 / mypy 10 / oxlint 1 baselines met (delta gates
  PASS); `git diff --check` clean.
- **Deployment/demo:** dev/demo runs on Docker Compose + Vite (currently up);
  Render.com is the documented demo target; Phase 4 production rails
  **deferred** (P4.1 CI/CD only is done).

## 3. Committed Work (recent)

| Commit | What |
|---|---|
| `e8735d7` | **feat: add vendors and purchase orders (M14)** — `vendors`, `purchase_orders`, `po_lines` + migration `k4c5d6e7f8a9`, vendor/PO routers + services, PO lifecycle + admin-only approve/reject, M8 idempotency, M13 PO notifications, `VendorsPanel`/`PurchaseOrdersPanel`, 13+32+6 tests. Pushed. |
| `36f166d` | **docs: add milestone plans and infrastructure decisions** — M6/M12/M13 plans, M6 review, P4.2 decision report. Pushed. |
| `13677fd` | **docs: add durable AI session context** — `docs/AI_CONTEXT.md`, `docs/SESSION_HANDOFF.md`. Pushed. |
| `7795890` | **test: close out client portal security boundary (M6)** — 7→17 tests. Pushed. |
| `3315957` | **feat: add in-app notifications and alerts (M13)** — `notifications` + migration `j8e9f0a1b2c3`. Pushed. |

Pre-M12 history is unchanged (see `git log`). No M15 commit exists yet.

## 4. Current Worktree State

M15 step-1 implementation (uncommitted; this session was told not to commit):

- **New:** `backend/alembic/versions/l5d6e7f8a9b0_m15_receiving_deliveries.py`,
  `backend/app/models/delivery.py`, `backend/app/schemas/delivery.py`.
- **Modified:** `backend/app/models/purchase_order.py` (POStatus +2 members;
  POLine.received_quantity/inventory_item_id), `backend/app/models/inventory.py`
  (StockMovement.po_line_id), `backend/app/models/finance.py`
  (JobCost.po_line_id), `backend/app/models/__init__.py` (Delivery/
  DeliveryLine exports), `backend/app/schemas/purchase_order.py` (POLineRead
  received fields), `backend/tests/test_migrations.py` (HEAD + assertions).
- **Docs:** `docs/AI_CONTEXT.md`, `docs/SESSION_HANDOFF.md` (regenerated to the
  M15-in-progress state), `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`,
  `docs/SESSION_NOTES.md`, plus the prior session's retained doc edits.
- No other application code changed; no migrations beyond `l5d6e7f8a9b0`.

## 5. M15 Implementation State (approved plan: `docs/M15_IMPLEMENTATION_PLAN.md`)

All 17 §33 owner decisions are **approved as written** (recommended defaults;
`CLOSED` status NOT included).

- **DONE (step 1):** migration + models + schemas + migration tests.
  Verified: full suite 307 green, migration chain (up/down/replay) green, ruff/
  mypy delta gates PASS, dev DB migrated to `l5d6e7f8a9b0`.
- **NEXT (plan §34 steps 4–10):** `services/receiving.py` (pure domain math +
  status derivation), receiving routes in `api/v1/purchase_orders.py`
  (`POST /{po_id}/receive` idempotency-protected; `GET .../deliveries[/{id}]`),
  cancel guard for PARTIALLY_RECEIVED/RECEIVED, `po_received` notification type
  + hook, `tests/test_receiving.py`, frontend (types → api.ts →
  PurchaseOrdersPanel), docs + smoke + `docs/M15_IMPLEMENTATION_REVIEW.md`.
- **Two approved-implementation notes from step 1:**
  - `POLineRead.received_remaining` is a plain field defaulting to 0 (the
    setattr doctrine, like `line_total`) — the PO serializer must attach the
    real value when rendering a PO; a Pydantic `computed_field` was avoided
    because it adds a mypy `[prop-decorator]` finding (fails the delta gate).
  - `deliveries.verified_by`/`created_by` are nullable columns with
    `ON DELETE SET NULL` (repo attribution-FK doctrine); the app layer always
    populates them.

## 6. Deferred Work

- **Phase 4 P4.2–P4.6 (production infrastructure):** IaC, managed Postgres/
  Redis, secrets, observability, Redis rate limiting, staging/GO-NO-GO gate.
  Blocked on owner approval of D1–D9 (recommended: GCP Cloud Run + Cloud SQL
  + Memorystore + Secret Manager + Workload Identity). See
  `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md`.
- **M15 out-of-scope (explicit non-goals):** real file/photo uploads + GCS
  signed uploads + presigned URLs (Phase 6), QR infrastructure, multi-location
  inventory (M16), 7-day demand forecast (M16), reversal/returns, receipt
  edit/delete (append-only). Evidence is a manual `reference` + optional
  `note`/`photo_reference` string.
- **Email/SMS/web-push notification delivery** (M13 is in-app only).
- **httpOnly refresh-cookie transport** (M9-deferred; needs HTTPS env).
- **Frontend automated/E2E tests** (Playwright smoke is Phase 4).
- **Phase 6/7/8** features — planned, not started.

## 7. Unresolved Owner Decisions

- **P4.2 D1–D9** (provider/IaC/DB/Redis/secrets/domain/backup/IAM/staging) —
  documented in `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md`.
- **Email/push notification delivery** (provider + secrets).
- **Whether to enable real Google-authenticated clients** immediately after M6
  close-out or wait for the Phase 4 staging/gate.
- **M15 §33 decisions — ALL APPROVED** (17 recommended defaults; no `CLOSED`).

## 8. Important Architectural Decisions (do not accidentally reverse)

Verified in the repository; treat as authoritative:

- **Phase 4 production infrastructure is deferred** (P4.1 only is done).
- **Render** is the documented feature/demo deployment target; local dev is
  Docker Compose + Vite. **Dev-workflow gotcha:** compose bind-mounts only
  `backend/app`; `alembic/versions` is baked into the image, so a stale image
  silently no-ops `alembic upgrade head` while live `app/` runs newer code.
  **Rebuild the backend image after every migration change**
  (`docker compose build backend && docker compose up -d backend`).
- **M14 POs are commitments, not expenditures:** no `job_costs` rows, no stock
  movements, no `budget_spent`/invoice effect; totals are server-derived and
  the `total == Σ line_total + tax` invariant holds under concurrency.
- **M15 (in progress):** a verified receipt is the ONLY path that releases PO
  quantity into inventory/costs; partial receiving supported; over-receiving
  rejected (400); receipts append-only; evidence by reference (no uploads).
- **M13 is in-app notifications only**; email/push deferred; notification
  creation is transactional with its triggering event.
- **M6 client boundary is server-enforced and test-pinned** (17 tests).
- **M9 session architecture and M11 Google auth remain authoritative.**
- **Migration discipline:** one linear Alembic chain; additive revisions;
  chain-tested upgrade/downgrade/replay; dev DB applies migrations at startup.

## 9. Known Risks / Technical Debt (top items)

- Production/deployment rails deferred (no IaC, secrets manager,
  observability, Redis-backed rate limiting, staging/gate); refresh token in
  `localStorage`; in-memory per-process rate limiting.
- Baseline tooling debt (must not increase): ruff 2, mypy 10, oxlint 1.
- Stale-image dev-workflow gotcha (fixed Aug 14; see §8) — recurred when the
  image predated a migration; rebuild is now the standard step.
- Non-blocking: sync `httpx` in async Google handlers; admin self/last-admin
  lockout guard; no frontend tests; audit-list index; two uniqueness stubs.
- M14 residual: PO idempotency finalizer duplicates a slice of
  `IdempotencyGuard.finish()`; no file-upload surface exists yet.
- Full details: `docs/CURRENT_STATE.md` §5–§8.

## 10. Source of Truth

- `docs/AI_CONTEXT.md` = bootstrap/navigation (regenerated this session).
- `docs/CURRENT_STATE.md` = current verified project state.
- `docs/ARCHITECTURE.md` = architecture/invariants (note: older, predates
  M10–M14 endpoints — verify endpoint surfaces in code).
- `docs/ROADMAP.md` = future direction.
- Milestone `*_IMPLEMENTATION_PLAN.md` = approved scope (before); canonical M14
  plan = `docs/M14_IMPLEMENTATION_PLAN.md`; M15 plan =
  `docs/M15_IMPLEMENTATION_PLAN.md` (approved, all 17 owner decisions).
- Milestone `*_IMPLEMENTATION_REVIEW.md` = implementation verification (after);
  M14 review status updated to committed/pushed `e8735d7`.
- `docs/SESSION_HANDOFF.md` = current-session continuation state.
- Code and tests are the ground truth; any doc conflict resolves in their
  favor.
