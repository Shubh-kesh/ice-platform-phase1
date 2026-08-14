# ICE Platform — AI Context

Primary bootstrap document for OpenCode/LLM sessions. Short, stable,
navigational. It does **not** replace the authoritative docs it points to.
Read the cited documents for detail; verify anything that matters against
code/tests (source code is the ground truth).

## 1. Project Purpose

**ICE (Intelligent Construction Engine)** is a multi-site residential
construction ERP managing ~10–15 projects at once: scheduling/Gantt, daily
site logs, inventory, job costing, milestone invoicing, computed project
health, and in-app notifications in one dashboard. Stack: React 19 + Vite SPA
(TanStack Query, axios) · FastAPI (async SQLAlchemy, asyncpg) · PostgreSQL 16
· Alembic · Docker Compose (dev). Single-service monolith; Redis is
provisioned but unused. Source of product vision:
`docs/PRODUCT_REQUIREMENTS.md`.

## 2. Current Repository State

- **Branch:** `claude-development`; **HEAD:** `e8735d7` (feat: add vendors and
  purchase orders — M14), **up to date with origin/claude-development**.
- **M14 (`e8735d7`) is committed AND pushed.** The M6 close-out (`7795890`)
  and M13 (`3315957`) are committed and pushed. Working tree carries only
  documentation housekeeping edits (see `docs/SESSION_HANDOFF.md`).
- **Alembic repository head:** `l5d6e7f8a9b0` (M15 `receiving/deliveries`).
  The migration chain (upgrade → downgrade → replay) is chain-tested through
  this revision in `backend/tests/test_migrations.py`
  (`HEAD_REVISION = "l5d6e7f8a9b0"`).
- **Live dev DB: verified at `l5d6e7f8a9b0`** (Aug 14, 2026) — Docker is up
  (`ice-platform-*` healthy); the dev DB was migrated from `j8e9f0a1b2c3` by
  rebuilding the backend image (see §10 dev-workflow note).
- **Backend tests:** **307 passing** (verified Aug 14, 2026 against real
  Postgres), including 13 M14 vendor, 32 M14 purchase-order, 18 notification,
  21 M12 scheduling, 20 M11 Google, 17 M6 client-portal, and the Alembic
  upgrade/downgrade/replay chain through `l5d6e7f8a9b0`.
- **Frontend:** `npm run build` passes; `npm run lint` passes with 1
  pre-existing warning (`auth-context.tsx` Fast Refresh).
- **Quality gates:** ruff 2 / mypy 10 / oxlint 1 baselines met (delta gates
  PASS); `git diff --check` clean.
- **Working tree:** prior docs housekeeping edits PLUS **M15 step-1
  implementation, uncommitted** — migration `l5d6e7f8a9b0`, `models/delivery.py`,
  `schemas/delivery.py`, PO/inventory/finance model + PO-line schema
  extensions, and `test_migrations.py` HEAD update. Receiving routes/service/
  notifications/frontend/smoke not yet implemented (M15 in progress — §12).
- **Phase 4 production infrastructure (P4.2–P4.6):** intentionally **deferred**
  (owner decisions pending; see §4). P4.1 (CI/CD quality gates) is complete,
  committed, and CI-verified.

## 3. Completed Milestones

Chronological (all committed unless noted):

- **Phase 1** — foundation: auth, RBAC (4 roles), projects CRUD, Command
  Center, audit trail, seed data.
- **Phase 2** — tasks (Gantt), daily site logs, inventory ledger, finance
  schema scaffold.
- **M1** — inventory integrity: row-locked movements + ledger reconciliation.
- **M2** — project-assignment management (unique constraint, admin API/UI).
- **M4** — job costing with cost codes; `budget_spent` derived from ledger.
- **M10** — project lifecycle & admin: DRAFT→ACTIVE→COMPLETED→ARCHIVED,
  auto project codes, archive visibility/read-only, seed gating.
- **M3** — computed health (timeline/budget/safety) + audited admin overrides.
- **M5** — milestone invoicing (schedule-of-values → invoices; client
  restricted shape).
- **M6** — client view-only portal (server-enforced contract). Close-out
  (`7795890`, 17 tests) — detail isolation, archived-404, task/site-log read
  shapes, invoice allow/deny lists, IDOR, mutation matrix,
  Google-authenticated-client parity, and a role regression.
- **M7** — task date-order + dependency/cycle validation.
- **M8** — idempotency keys (transactional claim ledger).
- **M9** — token security: opaque rotated refresh sessions, revocation,
  deactivated cutoff, auth-event audit.
- **M11** — Google Sign-In (Authorization Code + PKCE, server-side ID-token
  verification, admin onboarding; real smoke verified).
- **M12** — dynamic Gantt: push-only Finish-to-Start scheduling, automatic
  cascade, `task_schedule_shift` audit.
- **M13** — in-app notifications & alerts (schedule/invoice/low-stock/
  assignment events; user-scoped feed API; AppShell bell).
- **P4.1** — CI/CD & quality gates (GitHub Actions; baseline-delta gates).
- **M14** — Vendors & Purchase Orders (`e8735d7`, pushed): global vendor
  master data (unique name → 409, soft deactivation, admin+procurement) and
  project-scoped POs with line items, server-derived totals, `PO-{code}-{seq}`
  numbering, audited DRAFT→PENDING_APPROVAL→APPROVED lifecycle (admin-only
  approve/reject), M8 idempotency on PO/line create, M13 PO notifications.
  **No receiving/verification, no job-cost/stock impact yet (M15).**
- **M15 — PO Delivery Verification / Receiving (IN PROGRESS, uncommitted):**
  step 1 (migration `l5d6e7f8a9b0` + models + schemas + migration tests)
  landed per `docs/M15_IMPLEMENTATION_PLAN.md`; receiving API/service/
  notifications/frontend/smoke pending. See §12.

## 4. Deferred / Explicitly Out-of-Scope Work

- **Phase 4 production infrastructure (P4.2–P4.6):** IaC (Terraform/Cloud
  Run), managed Postgres/Redis, secrets management, observability,
  Redis-backed rate limiting, staging/GO-NO-GO gate — explicitly postponed.
  Decision report: `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md` (D1–D9 owner
  decisions unapproved); plan: `docs/PHASE4_IMPLEMENTATION_PLAN.md`.
  **Recommended stack (unapproved):** GCP Cloud Run + Cloud SQL + Memorystore
  + Secret Manager + Workload Identity.
- **M14 deferred scope (Phase 5):** delivery verification/receiving (M15),
  multi-location inventory (M16), 7-day demand forecast (M16), vendor
  performance tracking (needs M15 delivery data).
- **Email/SMS/web-push notification delivery** — M13 is in-app only; external
  delivery needs a provider + secret management (deferred).
- **7-day low-stock demand forecast** — static reorder-threshold alerts only;
  forecast is Phase 5 (needs a worker).
- **Phase 5** (vendors/POs done M14; receiving M15; locations/forecast M16),
  **Phase 6** (daily-log photos + voice-to-text, offline, quality hold-points,
  attendance), **Phase 7** (AI/ML), **Phase 8** (scale/SSO/compliance) —
  planned, not started beyond M14.
- **httpOnly refresh-cookie transport** — M9-deferred; requires HTTPS env.
- **Frontend automated/E2E tests** — deferred (Playwright smoke is Phase 4).

## 5. Current Production/Demo Architecture

- **Development/demo:** Docker Compose (PostgreSQL 16, Redis 7, backend on
  `:8000` via gunicorn/uvicorn); frontend served by Vite dev server on
  `:5173`. Redis is provisioned but **unused by any code**. **Docker/dev DB
  is currently down** — start `docker compose up -d postgres` before relying
  on the live DB.
- **Deployment target (documented, not built):** Render.com for feature/demo
  per the roadmap; Phase 4 production rails (IaC/secrets/observability) are
  deferred. GCP/Cloud Run is the recommended Phase 4 stack (unapproved).
- **Migrations** run at container startup (`alembic upgrade head`) in dev;
  `alembic/env.py` reads DB credentials from app settings (single source of
  truth).

## 6. Authoritative Documentation Hierarchy

| Purpose | Document |
|---|---|
| LLM bootstrap/navigation | `docs/AI_CONTEXT.md` (this file) |
| Current verified project state (facts, tests, limitations) | `docs/CURRENT_STATE.md` |
| System architecture and invariants | `docs/ARCHITECTURE.md` |
| Milestone direction and sequencing | `docs/ROADMAP.md` |
| Historical development/session record | `docs/SESSION_NOTES.md` |
| Approved milestone scope **before** implementation | `docs/M*_IMPLEMENTATION_PLAN.md` |
| Post-implementation verification (what was actually done) | `docs/M*_IMPLEMENTATION_REVIEW.md` |
| Current-session continuation state (temporary) | `docs/SESSION_HANDOFF.md` |
| Product vision | `docs/PRODUCT_REQUIREMENTS.md` (SRS-derived) |
| Prior comprehensive audit | `docs/TECHNICAL_AUDIT.md` |
| Phase 4 infrastructure decision pass | `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md` |

Order of trust: **code/tests > CURRENT_STATE.md > milestone reviews > plans >
ROADMAP.md > older docs**. `ARCHITECTURE.md` is older (Aug 9) and predates
M10–M14 endpoints; treat its structure as valid but verify current endpoint
surfaces in code.

## 7. RBAC / Security Invariants

- **Roles are ICE-owned.** Google authentication (M11) never grants or changes
  a role; Google identity is authoritative via `users.google_sub` (unique),
  and verified email is only a link path — never the identity key.
- **4 roles:** `admin`, `site_supervisor`, `procurement_manager`, `client`.
  Admin+procurement see all projects; supervisor/client only assigned ones
  (`project_access.assert_can_view_project`). ARCHIVED projects are 404 to
  non-admin/procurement (never leaked).
- **Client isolation is server-side (M6):** clients get only the
  `ProjectClientRead` / `InvoiceClientRead` shapes; money/health/inventory/
  finance/milestone surfaces are 403; clients can never mutate anything
  (mutation matrix pinned by 17 M6 tests).
- **M9 session architecture is authoritative:** opaque refresh tokens stored
  only as SHA-256 digests, row-locked rotation, family revocation on reuse,
  server-side logout, deactivated-user cutoff; access JWTs stay stateless.
  httpOnly-cookie transport deferred.
- **Lifecycle/archive (M10):** status moves only through audited admin
  transitions; no hard deletes (soft lifecycle only).
- **Transactions + locking:** mutations commit their data change + audit row
  atomically; project-scoped writes (tasks, inventory movements, job costs,
  lifecycle, invoicing, scheduling, purchase orders) serialize on a project
  row lock; a failed request never leaves a half-applied change. Inventory
  movements additionally lock the item row; PO transitions lock the project
  then the PO row.
- **Audit:** `record_audit()` in the same transaction as the mutation; no
  second audit system. `audit_logs` and `daily_site_logs` are append-only
  (no update/delete endpoints).
- **Money** = `Numeric(14,2)`; quantities `Numeric(12,2)`; inventory ledger
  (`stock_movements`) is immutable and the source of truth. PO totals are
  server-derived; the invariant `total_amount == Σ line_total + tax_amount`
  holds under concurrent line edits (test-pinned).
- **Migration discipline:** additive Alembic revisions in one linear chain;
  upgrade/downgrade/replay is chain-tested; destructive downgrades guarded.

## 8. Database / Migration State

- **Repo Alembic head = `l5d6e7f8a9b0`** (M15 `deliveries`/`delivery_lines` +
  `po_status` extension). **Live dev DB verified at the same revision** (Aug 14,
  2026) — migrated via a backend image rebuild after the stale-image fix; run
  `alembic current` / `alembic heads` inside the container to re-check.
- **M14 migration** adds `vendors` (unique name, `is_active`), `purchase_orders`
  (project FK, vendor FK, status enum, PO number, totals/tax, lifecycle
  columns), `po_lines` (qty/price/cost_code), plus PO numbering/totals
  backstops. No existing-table changes.
- **M15 migration** extends `po_status` additively (`PARTIALLY_RECEIVED`/
  `RECEIVED`), adds `po_lines.received_quantity`/`inventory_item_id`,
  `stock_movements.po_line_id`, `job_costs.po_line_id`, and new
  `deliveries`/`delivery_lines` tables (append-only receipt evidence). No
  destructive existing-table changes; no backfill.
- Migration chain (14 revisions): `5d2e53a7df4e` (initial) →
  `8f3a1c2d9e01` (Phase 2) → `a4b6c8d9e2f3` (M1) → `b5c7d9e1f203` (M2) →
  `c6d8e0f2a415` (M4) → `d7e9f1a2b3c4` (M10) → `e8f2a3c5b7e4` (M3) →
  `f3a4b5c6d7e8` (M8) → `g5b6c7d8e9f0` (M5) → `h6c7d8e9f0a1` (M9) →
  `i7d8e9f0a1b2` (M11) → `j8e9f0a1b2c3` (M13) → `k4c5d6e7f8a9` (M14) →
  `l5d6e7f8a9b0` (M15). M6/M7/M12 had no migration.

## 9. Test / Quality Baseline

- **Backend:** `pytest` (async, real Postgres; disposable `ice_test_db`):
  **307 passing** (verified Aug 14, 2026). Includes the migration-chain test
  (`backend/tests/test_migrations.py`) through `l5d6e7f8a9b0` (M15).
- **Frontend:** `npm run build` (tsc + vite) passes; `npm run lint` (oxlint)
  passes with 1 pre-existing `auth-context.tsx` Fast-Refresh warning.
- **Lint/type debt (gated, not fixed):** ruff 2 and mypy 10 pre-existing
  findings in `.ci/baseline_{ruff,mypy}.txt`, oxlint 1 in
  `.ci/baseline_oxlint.txt`. Enforced as a CI delta gate (P4.1) via
  `scripts/ci_quality.py` — **new findings fail the gate; baseline debt must
  not increase** and may only be reduced by deleting genuinely-fixed lines.
- **CI:** `.github/workflows/ci.yml` runs on PR/push: ruff, mypy, pytest
  (incl. migration chain), `git diff --check`, frontend build + oxlint.
- **Coverage:** ~75% overall; no frontend tests.
- **Commands:** backend `cd backend && pytest tests/ -v` (requires Postgres;
  Docker compose or a local PG with `ice_test_db`); frontend
  `npm run build` / `npm run lint`. Note: `pytest` is **not** installed in the
  Docker runtime image — run tests from the host.

## 10. Current Known Technical Debt / Risks

- Pre-existing lint/type baseline: ruff 2, mypy 10, oxlint 1 (must not
  increase).
- Refresh token in `localStorage` (XSS surface; M9-deferred httpOnly cookie).
- Rate limiting is in-memory/per-process (Phase 4 item).
- Synchronous `httpx` in async Google callback handlers (M11 residual).
- Admin self/last-admin deactivation unguarded (M11 residual).
- No frontend automated tests; audit listing lacks an index; a few DB
  uniqueness stubs remain (`inventory_items(project_id,name)`,
  `daily_site_logs(project_id,log_date)`).
- M14 residual: the PO idempotency finalizer duplicates a small slice of
  `IdempotencyGuard.finish()` (would need a matching update if M8 adds record
  columns); no file-upload surface exists yet (any M15 photo-evidence path
  must be designed safely — type/size validation, signed GCS URLs).
- Dev-workflow gotcha (fixed Aug 14): the compose backend bind-mounts only
  `backend/app`, so `alembic/versions` is baked into the image. A stale image
  silently no-ops `alembic upgrade head` while the live `app/` runs newer code
  — the `relation "vendors" does not exist` class of error. **Rebuild the
  backend image (`docker compose build backend`) after every migration change**,
  then `docker compose up -d backend`.
- Full list: `docs/CURRENT_STATE.md` §5–§8.

## 11. Remaining Feature Roadmap

From `docs/ROADMAP.md` (Phase 5 → Phase 8). Phase 4 production rails are
deferred pending owner decisions.

- **Phase 5 — Procurement & Multi-Location Inventory:** (M14 vendors/POs
  DONE) — M15 delivery verification/receiving (QR/photo-verified receipt
  releasing stock + cost entries), M16 warehouse/transit/site location
  dimension + ledgered transfers, M16 7-day low-stock forecast, vendor
  performance tracking (needs M15 delivery data).
- **Phase 6 — Field Experience:** photo upload + gallery per daily log, voice
  capture, offline-first PWA with sync/conflict resolution, quality
  hold-points/phase gates, attendance + toolbox talks, mobile-first UI.
- **Phase 7 — AI/ML:** data pipeline, predictive delay-risk with confidence +
  human-review trail, CV QC anomaly detection, drawing→BOQ suggestions.
- **Phase 8 — Scale & Maturity:** regional compliance reporting, portfolio
  forecasting, SSO/OIDC beyond Google, multi-tenant.

Sequencing guardrail: no phase ships to production without Phase 4 rails; if a
cut is forced, preserve Phase 3 → Phase 4 → Phase 6 → Phase 7 (procurement is
the most safe to trim/reorder).

## 12. Current Milestone — M15 (in progress)

**M15 — PO Delivery Verification / Receiving** (Phase 5 milestone 2):
verified receipt against PO lines is the only path that releases stock into
inventory + creates `job_costs` entries. Reuses the M1 ledger, M8 idempotency,
M13 notifications, M10 lifecycle gating; no Phase 4 infrastructure dependency.
**Approved plan:** `docs/M15_IMPLEMENTATION_PLAN.md` (all 17 §33 owner decisions
approved; `CLOSED` status NOT included).

**Status — step 1 landed, uncommitted:** migration `l5d6e7f8a9b0` + M15 models
(`Delivery`/`DeliveryLine`; `POStatus` extension; PO-line/inventory/job-cost
columns) + schemas (`schemas/delivery.py`, PO-line received fields) +
migration-chain tests. Receiving routes/service, notifications, frontend, and
smoke tests are the remaining steps.

**Approved M15 scope:**
- **Verified receiving/release first:** mark PO lines received
  (`received_quantity`, `stock_movements.po_line_id`, `job_costs` release),
  partial-receipt semantics (a 2-of-3-line PO releases only the verified
  lines), server-derived quantities.
- **Photo-reference/manual evidence, NOT full GCS upload:** no file-upload
  surface exists yet; the full GCS signed-upload pipeline is a Phase 6 item.
  M15 should use a photo *reference* / manual-verify evidence field, deferring
  real file storage to Phase 6.
- **Extension:** `POStatus` extended additively (e.g. `PARTIALLY_RECEIVED` /
  `RECEIVED`); notification + audit hooks; vendor-performance data collection
  seeds.

**Next step:** M15 receiving service + API (plan §34 sequence), then
notifications, frontend, smoke tests, and the
`docs/M15_IMPLEMENTATION_REVIEW.md` record.

## 13. How a Fresh OpenCode Session Must Reconstruct Context

1. Read `docs/AI_CONTEXT.md` (this file).
2. Read `docs/CURRENT_STATE.md` and `docs/ROADMAP.md`.
3. Read `docs/SESSION_HANDOFF.md` (if present) for the latest continuation
   state — it is a snapshot, not authority over code/tests.
4. Read the relevant milestone implementation plan (before) / review (after)
   for the active milestone.
5. Inspect `git status`, `git log --oneline -5`, and branch tracking.
6. Verify `alembic current` matches the repo head **after starting Docker**
   (the dev DB is currently down); reconcile the dev DB if it lags. Do not
   claim live-DB state you have not verified.
7. Confirm test/quality baselines (pytest count, frontend build/lint, CI
   gates) match the documented numbers before declaring work complete.
8. Do not implement anything until the current milestone and its approved plan
   are understood; never silently expand milestone scope.
9. Do not modify an approved implementation plan after implementation begins.
10. Do not commit or push unless explicitly instructed.

## 14. Context Compaction / Handoff Protocol

```
NORMAL SESSION
  → read AI_CONTEXT
  → inspect relevant docs/code
  → work on current task

AT ~70–80% CONTEXT
  → stop major implementation
  → create/update docs/SESSION_HANDOFF.md
  → record exact current state and next action
  → start fresh session

NEW SESSION
  → read AI_CONTEXT
  → read CURRENT_STATE
  → read SESSION_HANDOFF (if present)
  → read the relevant milestone plan/review
  → inspect git status
  → continue only after reconstructing state
```

Update `docs/SESSION_HANDOFF.md` as a **fresh, current-only** document at every
handoff — never carry stale HEAD hashes or test counts forward.
