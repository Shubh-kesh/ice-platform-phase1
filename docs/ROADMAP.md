# Product Roadmap — from Current State to Product Vision

**Inputs:** `docs/PRODUCT_REQUIREMENTS.md` (vision), `docs/CURRENT_STATE.md` (reality), `docs/ARCHITECTURE.md` (implementation).
**Date:** August 9, 2026
**Method:** Phases are designed to close **critical architecture gaps → data integrity → security → core business workflows → production readiness → scalability → AI/ML**, in that order. They are **not** a continuation of the original SRS numbering.

---

## Prioritization legend

| Tag | Meaning |
|---|---|
| **MUST HAVE** | Required to make the platform trustworthy, usable for real work, or secure. Gating for later phases. |
| **SHOULD HAVE** | Clear business value, but can land slightly later without blocking critical path. |
| **NICE TO HAVE** | Differentiators / efficiency features; defer if scope slips. |

---

## Phase 3 — Integrity, Operable RBAC & the Finance Pillar

**Goal:** Make existing functionality trustworthy and operationally real: no lost stock updates, real per-project access control, and the finance pillar that the current schema only scaffolds. This is the "make it correct" phase.

**Business value:** High. Stock numbers become reliable; users can actually be onboarded per site; budgets become real (computed, not typed); milestone invoices generate revenue paperwork automatically.

**Features**
- **MUST:** Row-locked inventory movements (`SELECT ... FOR UPDATE`) + periodic ledger reconciliation.
- **MUST:** Project-assignment management API + UI (assign/unassign users to projects; admin-only).
- **MUST:** Project health computed from real signals (schedule vs. dates → timeline; job costs vs. budget → budget; site safety flags → safety) with manual-override permitted + audited.
- **MUST:** Job Costing — create/list `JobCost` entries with a **cost-code enum** (masonry, plumbing, etc.); `Project.budget_spent` derived from job costs (+ manual adjustment only if unavoidable).
- **MUST:** Invoicing — `Invoice` CRUD; milestone → invoice generation rules (e.g., "Slab Completed → 20%").
- **SHOULD:** Client view-only access: invoices + progress, no budget figures (role-scoped response contract).
- **SHOULD:** Task date-order validation on update + dependency cycle detection.
- **SHOULD:** Idempotency keys on POSTs (movements, site logs, invoices).

**Dependencies:** existing `job_costs`/`invoices` tables, `project_assignments`, `project_access.py` helper, `record_audit()`.

**Architecture changes**
- Introduce a thin `services/` layer for the finance + health computation logic (first step away from inline handler logic).
- Health computation can run synchronously on read/write for Phase 3 (no worker yet).

**Database changes**
- `job_costs`: add `cost_code` (enum/string) column; index `(project_id, incurred_on)`.
- `invoices`: add `milestone_definition`/`contract_mapping` reference; keep `external_*` columns.
- Unique constraints: `project_assignments (project_id, user_id)`; `inventory_items (project_id, name)`; `daily_site_logs (project_id, log_date)` (or allow-override policy column).
- `stock_movements` + `audit_logs`: add composite indexes for listing (`created_at DESC`).
- Alembic migration for all above.

**API changes**
- `POST/DELETE /api/v1/projects/{id}/assignments` (admin) — or `PATCH /api/v1/users/{id}/assignments`.
- `GET/POST /api/v1/projects/{id}/job-costs`, `GET /api/v1/projects/{id}/budget` (computed roll-up).
- `GET/POST/PATCH /api/v1/projects/{id}/invoices`.
- Health fields: computed + override endpoint (`PATCH /api/v1/projects/{id}/health-override`).
- `Idempotency-Key` header handling on movement/log/invoice POSTs.

**Frontend changes**
- Project Detail: Job Costs panel (add/list with cost code), Invoices panel, budget vs. spent computation.
- Admin user management: assign supervisors/clients to projects.
- Client view house view: replace budget figures with photos/invoices per Phase 6 landing earlier if scope permits.
- Surface mutation errors consistently (replace silent failures + `alert()`).

**Testing requirements**
- **MUST:** `test_projects.py` (CRUD, PATCH RBAC incl. assigned-only supervisor, health override audit).
- **MUST:** Finance tests (cost create/roll-up correctness, milestone invoice generation, invoice RBAC incl. client read isolation).
- **MUST:** Inventory concurrency test (two parallel movements → both reflected; no lost update).
- **MUST:** Assignment API tests (admin-only, isolation effects on supervisors/clients).

**Security considerations**
- Role-scope project responses per role; never leak `budget_*` to client.
- Idempotency-key validation (server-side key namespace per user).
- Audit every finance and assignment write.
- Continue token work: **refresh-token rotation + server-side revocation** + optional httpOnly cookie (security debt from Phase 1; do in this phase — see acceptance).

**AI/ML considerations:** none required. But record **structured** cost data (cost codes, milestone events) — this becomes a future feature.

**Acceptance criteria**
- Two concurrent consumptions of the same item both persist; ledger sum equals `quantity_on_hand`.
- A supervisor/client blocked from projects after unassignment within one request.
- `Project.budget_spent` equals `SUM(job_costs)`; milestone completion creates the configured `%` invoice as draft.
- Client role cannot read any budget field; can read own invoices.
- No audit row missing `ip_address`; refresh tokens rotate and deactivated users are cut off immediately.

---

## Phase 4 — Operational Control & Production Readiness

**Goal:** Everything can be deployed, monitored, backed up, and changed safely by one person (the operator). Also: background jobs for scheduled computation.

**Business value:** Low-to-medium direct value, but **gating**: without this, nothing above is safely usable with real money at risk.

**Features**
- **MUST:** CI/CD — GitHub Actions: lint (ruff + oxlint) + typecheck (mypy/tsc) + `pytest` + coverage gate + frontend build; PR/merge gates.
- **MUST:** IaC + deploy — Terraform (or Cloud Run YAML) for backend + managed Postgres + secrets.
- **MUST:** Secrets management (Secret Manager) — no secrets in compose/env files.
- **MUST:** Structured logging (request IDs, JSON to Cloud Logging), error tracking (Sentry or equivalent), uptime + latency alerting.
- **MUST:** Backups — managed Postgres PITR + point-in-time restore runbook.
- **MUST:** Rate limiting fixed: Redis-backed limiter keyed on forwarded client IP, validated under 4+ workers.
- **SHOULD:** Lightweight background job runner (see below) for health computation and stale-data cleanup.
- **NICE TO HAVE:** Load test at 15-project profile; pagination+indexes on list endpoints.

**Dependencies:** Phase 3 (correctness before deployment confidence); Token/security fixes from Phase 3.

**Architecture changes**
- Introduce a worker/queue for scheduled jobs: Redis already provisioned → adopt Celery (or a simple `asyncio` scheduler on one worker) for **health recomputation** and **stale-flag sweeps**.
- Keep workers lightweight; no event sourcing yet.

**Database changes**
- None required beyond indexes (do cursor pagination on `audit_logs` and any list endpoint reaching scale).

**API changes**
- `X-Request-ID` on all responses; structured error event payload.
- Health recompute now served by worker (endpoint becomes read-only).

**Frontend changes**
- Build/deploy pipeline integration (env-based API URL); no feature work required.

**Testing requirements**
- Backend "does it boot in prod-like config" smoke test; CI coverage gate > 70% (raise to 80%).
- Rate-limiter integration test simulating proxy headers + multi-worker.
- Restore-from-backup drill (scripted).
- E2E: Playwright smoke (login → command center → project detail) in CI.

**Security considerations**
- Secrets rotation runbook; container image scan; dependency audit (`pip-audit` / `npm audit`).
- TLS at edge; HSTS; secure cookie flags if httpOnly refresh adopted in Phase 3.

**AI/ML considerations:** ensure image/photos (Phase 6) and structured events (Phase 3 finance) are being stored in aggreable form — this is the data-collection foundation for Part 13 (AI).

**Acceptance criteria**
- A PR that fails ruff, mypy, tsc, or tests is blocked.
- Deploy is scripted end-to-end from empty Terraform state; secrets never in repo.
- Rate limit of 5/min holds per-user behind an LB with 4 workers.
- Backup restore verified in a controlled env; alerts fire on 5xx bursts.

---

## Phase 5 — Procurement & Multi-Location Inventory

**Goal:** The procurement pillar: purchase orders, delivery verification, and inventory spanning warehouse → transit → site with schedule-driven restocking.

**Business value:** High — this is where material spend is controlled; PO verification prevents paying for unverified goods; 3-location tracking reduces stockouts/misplacement across 15 sites.

**Features**
- **MUST:** Vendor entity (name/contact/payment terms) + vendor performance tracking (on-time %, price).
- **MUST:** Purchase Order entity (vendor, lines, quantities, project, status) + PO lifecycle.
- **MUST:** Delivery verification — QR-code scan **or** photo-verified receipt against PO lines; verified receipt releases stock into inventory and triggers cost entries.
- **MUST:** Location dimension: `warehouse` / `transit` / `site` for inventory; transfers between locations recorded as movements.
- **MUST:** Low-stock **forecast** alerts using next-7-days-scheduled demand (from tasks + BOQ/BOM) rather than static thresholds.
- **SHOULD:** Approval workflow: Procurement creates PO → (optional) Admin approve → receive.
- **NICE TO HAVE:** Cross-project inventory roll-up view for Procurement.

**Dependencies:** Phase 3 (correct inventory semantics, cost-code integration), Phase 4 (worker for demand forecast).

**Architecture changes**
- Extend the services layer (Idempotency + ledger service gets the receipt/forecast logic).

**Database changes**
- New tables: `vendors`, `purchase_orders`, `po_lines`, `deliveries` (+ `delivery_lines` or reuse), `inventory_locations`.
- `inventory_items`: add `location_id`/`location_type`; `stock_movements`: add `po_line_id` nullable + `location_from/location_to` for transfers.
- Indexes on `(location, project)`, `(po, status)`.

**API changes**
- `/vendors` CRUD; `/purchase-orders` CRUD + line ops + status transitions.
- `POST /deliveries/verify` (QR payload or photo ref) → returns verification result.
- `GET /inventory?location=warehouse|transit|site`.
- `GET /projects/{id}/low-stock` (schedule-demanded) or push via notification (deferred to Phase 6 infra).

**Frontend changes**
- Procurement workspace: vendor/PO forms, receive-and-verify UI (camera scan or photo pick), location filter.
- Low-stock dashboard (flag which site will run out in 7 days).

**Testing requirements**
- PO lifecycle state-machine tests; verification logic (QR vs photo); release-to-stock + cost entry side effects; transfer ledger correctness; demand-calculation unit tests.

**Security considerations**
- Photo upload now exists → siz/type validation, signed GCS URLs, content-type enforcement (deferred from earlier — MUST here).
- PO amount/tax fields; approve-step RBAC (Admin vs Procurement).
- Vendor objects: no PII exposure beyond intended roles.

**AI/ML considerations:** vendor performance + on-time history begins to accumulate — this unblocks **predictive delay** (feature 2) later. Material consumption patterns feed future BOQ validation.

**Acceptance criteria**
- A PO with 2 of 3 lines verified only releases verified lines to stock + costing.
- Inventory queryable at warehouse/transit/site resolution; transfers fully ledgered.
- For any site + material, the system predicts stockout within 7 days and flags it.
- QR/photo verification is the only path that releases stock (no unverified receipt path).

---

## Phase 6 — Field Experience: Mobility, Photos & Quality/Safety Hold-Points

**Goal:** Site supervisors can actually run the field workflow from a phone — offline-capable — and quality gates are enforced. This delivers the PRD's offline-first + photo + hold-point pillars.

**Business value:** Very high for on-the-ground utility. Photographic QC evidence, gated phase progression, and attendance/toolbox compliance — the "field glue" that makes the rest of the system trustworthy.

**Features**
- **MUST:** Photo upload + gallery per daily site log (min 5 photos, per PRD): mobile camera, GCS presigned upload, thumbnail serving.
- **MUST:** Voice-to-text summary capture for daily logs (on-device or API STT with human edit).
- **MUST:** Offline-first: PWA + local cache/queue for site logs/checklists with **auto-sync** on reconnect and conflict resolution (last-write-wins with audit note, or per-user-GUID resolution).
- **MUST:** Quality "hold-points": inspection checklist templates with mandatory photo evidence; phase sign-off that **blocks progression** to next phase until previous hold-point is digitally signed.
- **MUST:** Safety compliance: worker attendance log + daily toolbox-talk records (who, when, site).
- **SHOULD:** Mobile-first layout rewrite of field screens (collapsible nav, thumb-friendly forms, quick photo capture).
- **NICE TO HAVE:** Push/email notifications for schedule changes and low-stock (the PRD's "vendor notification" and alerting, finally wired).

**Dependencies:** Phase 5 (locations/POs make inventory data complete for field capture taste), Phase 3 (health/assignments make gating meaningful). Photos are independent; can be pulled earlier if field priority demands.

**Architecture changes**
- Introduce objected storage (GCS) + signed-URL service + image-processing (thumbnail).
- Introduce a **sync/queue** mechanism for offline (could reuse Redis queue workers from Phase 4, plus frontend service worker).
- Notification bridge (email provider or web push) — first real external integration.

**Database changes**
- `daily_site_logs`: keep `photo_urls` (now real); add `voice_summary` (text), `sync_status`, `client_guid` (offline collision key).
- New: `attachment`/`photos` table (or keep JSONB + resolve deltas).
- New: `checklists`, `inspection_items`, `inspections` (+ photos, sign-off user/time), `phase_gates` on tasks/projects.
- New: `attendance_events`, `toolbox_talks`.
- JSONB `changes` additions for offline-edit audit.

**API changes**
- `POST /files` (presigned upload), `GET /files/{id}` (view).
- `POST/PATCH /site-logs/{id}` now allowed (draft→final) with audit; offline sync endpoint (`POST /sync` bulk with client GUIDs).
- `GET/POST /projects/{id}/inspections`, `POST /projects/{id}/inspections/{iid}/signoff` with photo requirement.
- `POST /attendance`, `POST /toolbox-talks`.
- `POST /notifications/preferences` (future).

**Frontend changes**
- PWA (manifest + service worker) with offline queue; camera + mic access; draft cache; conflict UI.
- Supervisor mobile views for logs/checklists/attendance; client portal shows photos + invoices (finalizing Phase 3 role split).

**Testing requirements**
- Offline sync integration tests (disconnect → capture → reconnect → merge; duplicates prevented via `client_guid`).
- Upload tests (size/type rejection, presigned expiry, storage isolation per project).
- Hold-point gate tests (blocked progression until signed off with photos); RBAC on sign-off.
- Attendance/toolbox CRUD + RBAC.

**Security considerations**
- **Upload hardening is critical here**: content-type sniff, max size, virus scan option, private-by-default GCS ACLs, presigned-URL expiry, per-project storage paths.
- Offline/conflict: ensure audit trail records the offline actor and device.
- PII in attendance/toolbox → retention + access scoping (only site personnel + admin).
- Voice-to-text transcripts are personal data — review privacy handling.

**AI/ML considerations:**
- **Now the image corpus exists** → this is the entry point for **CV QC (feature 1)** next phase (photo → anomaly detect storage side).
- Structured weather (add per-log weather enum + forecast pull later) and attendance data begin to feed **predictive-delay** features.

**Acceptance criteria**
- A supervisor captures a full daily log (≥5 photos + voice summary) fully offline and it syncs with no duplicates.
- Phase 2 work cannot progress until Phase 1 inspection is signed off with photo evidence.
- Every toolbox talk + attendance record is timestamped, attributable, and visible to the responsible roles.
- Scheduled-change / low-stock notifications are delivered (push/email).

---

## Phase 7 — AI/ML Capabilities

**Goal:** Deliver the intelligent layer — predictive delay (feature 2) first, then CV QC (feature 1), then drawing→BOQ (feature 3) — with the human-review + audit guarantees the PRD requires.

**Business value:** Differentiator. Drives proactive resourcing (predictive delays), quality safety-net (CV QC), and speed-to-quote (BOQ). All three must be **non-authoritative suggestions with human sign-off** per PRD.

**Features**
- **MUST (data-prep):** Feature/data pipeline: structured extraction from Phase 3–6 data (schedule history, weather enum, vendor performance, attendance, photos). Async processing via Phase 4 worker or a dedicated model worker.
- **MUST:** Predictive delay — model trained on historical tasks/vendor/weather; API returns delay-risk per project/task with **confidence + feature explanation**; human review trail.
- **SHOULD:** CV QC anomaly detection — given site photos, flag probable defects (e.g., rebar spacing vs. design) as review items; store model output + confidence + image reference.
- **NICE TO HAVE:** AI BOQ generation from architectural PDFs/drawings into inventory demand + PO suggestions; human-accepted estimate becomes BOQ.

**Dependencies:** Phase 5/6 data (vendor history, weather, photos), Phase 4 workers, and GCS storage from Phase 6.

**Architecture changes**
- Add model-serving boundary: dedicated ML service (container) behind same API, or in-process with cold-start handling.
- Introduce `model_runs` audit table (model-id, input snapshot, confidence, status, reviewer).
- Add inference queue via Redis (already present) — jobs async, results fetched later by frontend.

**Database changes**
- New: `model_runs` (model_id, version, input_ref JSONB, output JSONB, confidence, review_status, reviewed_by, reviewed_at).
- Optional: `prediction_targets` linking runs to tasks/projects/invoices.
- Feature dataset snapshots exported to Parquet/GCS for retraining.

**API changes**
- `POST /ml/delay-risk/{project}` (or task) → async job + result poll.
- `POST /ml/qc/{photo_id}` → flag + store if confirmed by reviewer.
- `POST /ml/boq/{document_id}` → draft BOQ; then `PATCH /boq/accept`.
- Feature-flag endpoint: enable/disable per feature enterprise-wide (PRD acceptance).

**Frontend changes**
- Risk badges in Command Center, QC review queue UI, BOQ draft editor with accept/edit/reject.

**Testing requirements**
- Model I/O contract tests, feature-flag tests, review-required-before-authoritative tests (no AI result is treated as final unless reviewed).
- Offline/error handling (worker-down fallback), dataset drift guard.
- Golden tests for each prediction/classification function (deterministic cases).

**Security considerations**
- Inference inputs restricted to assigned roles/projects (reuse project_access); model endpoints rate-limited like auth.
- Prompt/side-channel hygiene: model inputs isolated per project; no cross-tenant leakage.
- Image/document inputs from GCS with signed access; prevent SSRF on any "fetch PDF" path.
- Audit every AI suggestion that becomes a record.

**AI/ML requirements (from PRD) covered here:** CV QC (5.1), predictive delay (5.2), BOQ (5.3), plus the acceptance criteria — model-id/input/confidence/human-review.

**Acceptance criteria**
- Delay-risk on an over/under-budget project matches hold-out predictions within agreed tolerance (exact threshold set with the owner).
- No QC flag or BOQ line is authoritative until a human confirms/rejects it, and that review is audited.
- All AI features are toggleable per-feature and per-enterprise, and every output records model id, input, and confidence.

---

## Phase 8 — Scale & Maturity (NICE TO HAVE / stretch)

**Goal:** Broaden the platform past the 15-project sweet spot and deepen compliance/forecasting.

**Business value:** Long-term optional. Unlocks portfolio-level cost forecasting, multi-region compliance, and op-scale ops.

**Features**
- **NICE TO HAVE:** Regionalized tax/retention reporting per local compliance.
- **NICE TO HAVE:** Portfolio-level forecasting (cashflow from invoices + committed POs).
- **NICE TO HAVE:** Advanced vendor/weather hybrid forecasting layered on Phase 7 model outputs.
- **NICE TO HAVE:** Multi-account/role-branded portals; SSO/SAML for organization.

**Dependencies:** Phase 7 model/data maturity; Phase 4/5 finance/procurement depth.

**Architecture changes:** Optional horizontal scaling (read replicas/instances), multi-tenant account model if client base diversifies.

**Database changes:** Multi-tenant `account_id` or schema scoping; compliance-reporting tables.

**API changes:** Versioned v2 as needed; SSO/OIDC support.

**Frontend changes:** Branded portals; portfolio analytics; SSO login flow.

**Testing requirements:** Cross-tenant isolation tests; compliance-report fixtures.

**Security considerations:** Cross-tenant isolation is the top risk; tenant-scoped keys everywhere; strict RBAC per account.

**AI/ML considerations:** Model retraining cadence + data pipeline automation.

**Acceptance criteria:** portfolio forecasts within tolerance; report outputs match provider schemas; multi-tenant isolation verified.

---

## Parting priorities summary

| | MUST HAVE (before scaling) | SHOULD HAVE | NICE TO HAVE |
|---|---|---|---|
| **Phase 3** | Row-locked ledger; assignments API; computed health; job costing + invoices; client role-scope; refresh rotation | health-override UI; task cycle detection | — |
| **Phase 4** | CI/CD; IaC+deploy; secrets; logging/monitoring; backups; rate-limit fix; structured errors | worker + scheduled health; pagination/indexing | load test; npm audit/pip-audit |
| **Phase 5** | Vendors/POs; QR/photo verification; 3-location inventory; schedule-driven low-stock; upload-hardening | PO approvals; roll-up view | forecast from weather |
| **Phase 6** | Photo+voice capture; offline-first sync; hold-point gating; attendance/toolbox; mobile-first UI | notifications (vendor/stock) | — |
| **Phase 7** | Data pipeline; delay-risk with review trail; feature flags; model_runs audit | CV QC review queue | BOQ generation; portfolio forecast |
| **Phase 8** | — | — | multi-tenant, compliance, SSO |

**Implicit guardrail:** no phase ships to production without the Phase 4 observability + CI + backup rails. If budget forces a cut, preserve: **Phase 3 (integrity/finance) → Phase 4 (production) → Phase 6 (field photos/offline) → Phase 7 (delay-risk)**; the procurement phase is the one most safe to trim/reorder.