# Product Roadmap — from Current State to Product Vision

**Inputs:** `docs/PRODUCT_REQUIREMENTS.md` (vision), `docs/CURRENT_STATE.md` (reality), `docs/ARCHITECTURE.md` (implementation).
**Date:** August 10, 2026
**Method:** Phases are designed to close **critical architecture gaps → data integrity → security → core business workflows → production readiness → scalability → AI/ML**, in that order. They are **not** a continuation of the original SRS numbering.

> **Aug 10 change:** two requirements added to **Phase 3** as mandates — **Project Lifecycle & Admin** (M10) and **Google Sign-In** (M11). Both were flagged after M4 shipped; they gate real-user rollout (M11) and make the Command Center and every downstream phase operate on lifecycle-aware, DB-driven projects instead of seed/demo data (M10). See the Phase 3 milestone sequence below.

---

## Prioritization legend

| Tag | Meaning |
|---|---|
| **MUST HAVE** | Required to make the platform trustworthy, usable for real work, or secure. Gating for later phases. |
| **SHOULD HAVE** | Clear business value, but can land slightly later without blocking critical path. |
| **NICE TO HAVE** | Differentiators / efficiency features; defer if scope slips. |

---

## Phase 3 — Integrity, Operable RBAC, Admin Lifecycle & the Finance Pillar

**Goal:** Make existing functionality trustworthy and operationally real: no lost stock updates, real per-project access control, admin-managed project lifecycle, and the finance pillar that the current schema only scaffolds. This is the "make it correct" phase, and it is also the **real-user rollout gate** (Google Sign-In lands here).

**Business value:** High. Stock numbers become reliable; users can actually be onboarded per site; budgets become real (computed, not typed); milestone invoices generate revenue paperwork automatically.

**Features**
- **MUST:** Row-locked inventory movements (`SELECT ... FOR UPDATE`) + periodic ledger reconciliation. *(DONE — M1)*
- **MUST:** Project-assignment management API + UI (assign/unassign users to projects; admin-only). *(DONE — M2)*
- **MUST:** Job Costing — create/list `JobCost` entries with a **cost-code enum** (masonry, plumbing, etc.); `Project.budget_spent` derived from job costs (+ manual adjustment only if unavoidable). *(DONE — M4)*
- **MUST:** **Project Lifecycle & Admin (NEW — M10)** — admin-managed, database-driven projects replacing seed/demo data as the permanent source. DRAFT → ACTIVE → COMPLETED → ARCHIVED lifecycle with no hard-deletes; auto-generated unique project codes; lifecycle-change audit (who/when); archived hidden from normal lists, retained in reporting; seed/demo data gated behind a dev-only flag.
- **MUST:** Project health computed from real signals (schedule vs. dates → timeline; job costs vs. budget → budget; site safety flags → safety) with manual-override permitted + audited. *(DONE — M3; ordered AFTER M10 so health only computes over ACTIVE projects; safety dimension is NOT_RATED until a structured safety/quality data model exists)*
- **MUST:** Invoicing — `Invoice` CRUD; milestone → invoice generation rules (e.g., "Slab Completed → 20%"). *(DONE — M5; ordered AFTER M10 so lifecycle gates invoicing on ACTIVE projects)*
- **SHOULD:** Client view-only access: invoices + progress, no budget figures (role-scoped response contract). *(DONE — M6 close-out: server-side contract verified with 17 client-portal tests incl. detail/archived isolation, IDOR, leakage, mutation protection and Google-client parity; before real clients use Google Sign-In)*
- **SHOULD:** Task date-order validation on update + dependency cycle detection. *(DONE — M7: date-order enforced on PATCH incl. partial updates; `depends_on_id` same-project/self/existence checks on update; 2- and 3-node cycle detection; task writes serialized via the project row lock so opposing concurrent links can't commit a cycle. App-layer only — no migration. See `docs/CURRENT_STATE.md` §4b)*
- **SHOULD:** Idempotency keys on POSTs (movements, site logs, invoices). *(DONE — M8: backend infra + `Idempotency-Key` header on POST job-costs, inventory movements, site-logs and project creation; `POST /projects/{id}/invoices` also protected since M5)*
- **MUST:** Token security — refresh-token rotation + server-side revocation + optional httpOnly cookie. *(DONE — M9: opaque refresh tokens (SHA-256 hashed in `refresh_sessions`), rotation under a row lock, server-side logout revocation, family-wide revocation on token reuse past a 10s grace window, deactivated-user cutoff at refresh, auth-event auditing with IP. httpOnly-cookie transport deliberately deferred — dev is cross-origin (`:5173` → `:8000`) and SameSite=None needs HTTPS. See `docs/CURRENT_STATE.md` §4b)*
- **MUST:** **Google Sign-In (NEW — M11)** — Google as **authentication only**; ICE retains identity, roles, authorizations, project assignments, permissions. Google never grants ADMIN. Session handling inherits M9 rotation/revocation/deactivation cutoff. Plans land here while Phase 4 provides the deploy/observability rails before real users arrive.

---

### Phase 3 milestone sequence (revised Aug 10)

Execution order (M1/M2/M4 shipped):

1. **M1 — inventory integrity** — DONE
2. **M2 — assignment management** — DONE
3. **M4 — job costing** — DONE
4. **M10 — Project Lifecycle & Admin** (NEW) — DONE. Foundation for everything that follows: DB-driven projects, lifecycle state machine + audit, archive visibility, seed gating. See `docs/CURRENT_STATE.md` §4b.
5. **M3 — computed health** — DONE. Reads lifecycle-aware project set (skip non-ACTIVE); deterministic Timeline/Budget verdicts + audited admin-only override (see `docs/CURRENT_STATE.md` §4b).
6. **M5 — invoicing** — DONE. Billing milestones (schedule of values) → server-side invoice amounts, lifecycle-gated (only ACTIVE generate; COMPLETED frozen; ARCHIVED hidden), client read-only restricted shape. See `docs/CURRENT_STATE.md` §4b.
7. **M6 — client view-only scope** — DONE (close-out verified; see CURRENT_STATE §4b). Before real clients authenticate.
8. **M7 — task validation** — DONE. Date-order on PATCH (full + partial), dependency same-project/self/existence on update, 2- and 3-node cycle rejection; task writes take the project row lock so concurrent opposing links can't form a cycle. App-layer only, no migration, no frontend change. See `docs/CURRENT_STATE.md` §4b.
9. **M8 — idempotency keys** — DONE. Server-side `Idempotency-Key` support on POST job-costs, inventory movements, site-logs and project creation: a retry replays the stored response (no double-mutation), a failed attempt frees the key, and concurrent same-key requests execute exactly once via a DB unique-index claim ledger. See `docs/CURRENT_STATE.md` §4b.
10. **M9 — token security** — DONE. Opaque hashed refresh sessions; rotation + server-side revocation + deactivated-user cutoff + reuse/theft family-revocation + auth-event audit; access tokens stay stateless JWT. Prerequisite for M11. See `docs/CURRENT_STATE.md` §4b.
11. **M11 — Google Sign-In** (NEW) — DONE in the application; real-user rollout still waits for Phase 4 production rails and a configured Google OAuth client.
12. **M12 — Dynamic Gantt & Dependency Scheduling** (NEW feature) — DONE. Push-only Finish-to-Start scheduling (`successor.start >= predecessor.end + 1`) auto-shifts dependents on task/dependency/date changes, transitively and idempotently, inside the project row lock; `task_schedule_shift` audit; timeline dependency picker + date editing + shift notice; clients read-only. No migration, no Phase 4 dependency. PRD §4.1.2 scheduling portion delivered; **vendor notifications** remain a separate gap.
13. **M13 — Notifications & Alerts** (NEW feature) — DONE. In-app, event-driven notifications: M12 schedule shifts → supervisors+admins, M5 invoice issued (payment request) → client+admins, inventory low-stock crossing → procurement+admins, M2 assignment → user. User-scoped feed/unread-count/mark-read/read-all API + AppShell bell; atomic with the event; M8 replay-safe; one migration (`j8e9f0a1b2c3`). PRD §4.1.2 notification portion delivered in-app; **email/SMS/push delivery** and the **7-day low-stock forecast** remain deferred (Phase 5 / external-provider decisions).
14. **M14 — Vendors & Purchase Orders** (Phase 5 first milestone) — DONE. Global vendor master data (unique name → 409, soft deactivation, admin+procurement) + project-scoped POs with line items, server-derived totals, `PO-{code}-{seq}` numbering, and the audited lifecycle DRAFT → submit → PENDING_APPROVAL → approve (admin) → APPROVED / reject (admin, reason) → REJECTED → revise | resubmit, plus cancel (A+P on DRAFT/PENDING; admin on APPROVED). Admin+procurement surface; supervisors/clients 403; M8 idempotency on PO/line create; M13 `po_submitted`/`po_approved`/`po_rejected` notifications. One migration (`k4c5d6e7f8a9`: `vendors`, `purchase_orders`, `po_lines`, `POStatus`). **Receiving/verification (M15), multi-location inventory (M16), demand forecast (M16) and vendor-performance tracking remain not started.** See `docs/M14_IMPLEMENTATION_REVIEW.md`.

Ordering rationale:
- **M10 before M3 and M5:** computed health and milestone invoicing must operate on a lifecycle-aware project universe (only ACTIVE compute health / generate invoices). Building them on the current seed-driven status model would force rework when lifecycle lands. Similarly, invoicing must not fire on COMPLETED/ARCHIVED projects.
- **M9 before M11:** Google only authenticates; ICE's JWT/session layer must already rotate + revoke refresh tokens and cut off deactivated users before external login is trusted with them.
- **M6 before real clients on Google:** Google-authenticated clients must never see budget fields, so the M6 role-scoped contract must exist before a real client signs in.

**Dependencies:** existing `job_costs`/`invoices` tables, `project_assignments`, `project_access.py` helper, `record_audit()`, auth `core/security.py`.

**Architecture changes**
- Introduce a thin `services/` layer for the finance + health + lifecycle computation logic (first step away from inline handler logic).
- Health computation can run synchronously on read/write for Phase 3 (no worker yet).
- Add an OAuth2/OIDC client (Google) behind the auth service; ICE keeps issuing its own JWT pairs (access + rotated refresh). Google identity is a secondary auth factor bound to an ICE user, never a role source.

**Database changes**
- `job_costs`: add `cost_code` (enum/string) column; index `(project_id, incurred_on)`. *(DONE — M4)*
- `invoices`: add `milestone_definition`/`contract_mapping` reference; keep `external_*` columns. *(DONE — M5: `billing_milestone_id` reference + unique `invoice_number` + partial double-billing index; see CURRENT_STATE.md §4b)*
- **(M10)** `projects`: add unique `project_code varchar` (auto-generated, e.g. `PRJ-YYYY-####`), lifecycle columns `created_by`, `status` extension to DRAFT/ARCHIVED (keep existing enum values + add), `completed_at`/`completed_by`, `archived_at`/`archived_by`, `restored_at`/`restored_by`. No hard deletes — a soft lifecycle, never `DELETE`.
- **(M10)** Add `is_demo`/seed marking OR a `seed_source` column so demo rows are identifiable and gagable; add `demo` flag to `seed.py` own runs (dev-only, env-gated).
- **(M9)** `refresh_sessions` table: one row per issued opaque refresh token (SHA-256 `token_hash`, `family_id` rotation chain, `parent_id`, `issued_at`/`expires_at`/`revoked_at`/`revoked_reason`, `ip_address`; unique token_hash, FKs user CASCADE / parent SET NULL, indexes on family/user+revoked/expires). *(DONE — migration `h6c7d8e9f0a1`)*
- **(M11)** `users`: add nullable `google_sub` (unique index) + `google_email` (read-only sync) + `password_hash_nullable` migration so Google-linked users can exist without a local password; keep `hashed_password` for retained username/password path. Google sessions join the existing `refresh_sessions` (keyed by `user_id` — no provider-specific columns).
- **(M3)** `health_overrides`: admin-set manual verdict per target (overall/timeline/budget/safety), optional `expires_at`, partial unique `(project_id, applied_to) WHERE revoked_at IS NULL`; widen `audit_logs.action` to varchar(100). *(DONE — migration `e8f2a3c5b7e4`)*
- Unique constraints: `project_assignments (project_id, user_id)` *(DONE — M2)*; `inventory_items (project_id, name)`; `daily_site_logs (project_id, log_date)` (or allow-override policy column).
- `stock_movements` + `audit_logs`: add composite indexes for listing (`created_at DESC`).
- Alembic migration for all above.

**API changes**
- *(M10)* `POST /projects` (admin, generates `project_code`, sets `created_by`, default DRAFT); `GET /projects` filters NON-ARCHIVED by default, `?include=archived` for admin; `GET/PATCH /projects/{id}`; lifecycle transitions as first-class audited actions: `POST /projects/{id}/activate`, `POST .../complete`, `POST .../archive`, `POST .../restore` (admin-only; each records who/when via `record_audit`). `PATCH` refuses lifecycle fields (status moves only via dedicated actions).
- *(M10)* `GET /projects/{id}` and reporting endpoints remain readable for COMPLETED; archived requires `?include=archived` + admin.
- `POST/DELETE /api/v1/projects/{id}/assignments` (admin) — or `PATCH /api/v1/users/{id}/assignments`. *(DONE — M2)*
- `GET/POST /api/v1/projects/{id}/job-costs`, `GET /api/v1/projects/{id}/budget` (computed roll-up). *(DONE — M4)*
- `GET/POST /api/v1/projects/{id}/billing-milestones`, `PATCH /projects/{id}/billing-milestones/{id}`, `POST /projects/{id}/billing-milestones/{id}/complete`, `GET/POST /projects/{id}/invoices`, `POST /projects/{id}/invoices/{id}/issue|mark-paid|cancel`. *(DONE — M5; admin owns, procurement view-only, clients read restricted shape)*
- Health fields: computed + override endpoint (`PATCH /api/v1/projects/{id}/health-override`). *(DONE — M3: `GET/POST/DELETE /projects/{id}/health-overrides` + `GET /projects/health` roll-up, both admin-only; computed verdicts stay visible; see CURRENT_STATE.md)*
- `Idempotency-Key` header handling on movement/log/invoice POSTs. *(DONE — M8: header handled on job-cost, movement, site-log, project-create and invoice POSTs)*
- *(M11)* `GET /auth/google/authorize` and `POST /auth/google/callback` use Authorization Code + PKCE, stateless HMAC state, nonce-bound server-side ID-token verification, and M9 session issuance. Unknown Google emails are rejected by default; verified email links preserve ICE roles and assignments.
- *(M11)* Admin creates a user without password (invitation): `POST /users` accepts no password when `google_only=true`; user links identity on first Google sign-in with matching verified email. `PATCH /users/{id}` supports role and audited activation/deactivation.

**Frontend changes**
- Project Detail: Job Costs panel (add/list with cost code), Invoices panel, budget vs. spent computation. *(DONE — M4 + M5)*
- *(M10)* Command Center: admin "Create Project" form (auto code display), lifecycle action menu (Activate / Complete / Archive / Restore) on project cards + detail; archive filter toggle for admin; completed projects keep appearing under reporting/completed filter.
- Admin user management: assign supervisors/clients to projects; *(M10 + M11)* invite flow (create without password, "pending Google link" status).
- Client view house view: replace budget figures with photos/invoices per Phase 6 landing earlier if scope permits. *(M6)*
- *(M11)* Login page: "Sign in with Google" button + `/google/callback` SPA route handling; keep username/password form alongside Google sign-in.
- Surface mutation errors consistently (replace silent failures + `alert()`).

**Testing requirements**
- **MUST:** `test_projects.py` (CRUD, PATCH RBAC incl. assigned-only supervisor, health override audit).
- **MUST:** `test_project_lifecycle.py` (M10) — DRAFT→ACTIVE→COMPLETED→ARCHIVED→RESTORE transitions valid/invalid validated; archived excluded from default lists but present in reporting + `?include=archived`; lifecycle transition RBAC (admin-only); audit rows carry actor + timestamp; project-code uniqueness + regeneration on retry; no hard-delete path exists for any state; historical child data (job costs, inventory, site logs, assignments) intact after COMPLETE/ARCHIVE.
- **MUST:** Finance tests (cost create/roll-up correctness, milestone invoice generation, invoice RBAC incl. client read isolation, lifecycle gating: no invoices generated for COMPLETED/ARCHIVED).
- **MUST:** Inventory concurrency test (two parallel movements → both reflected; no lost update).
- **MUST:** Assignment API tests (admin-only, isolation effects on supervisors/clients).
- **MUST:** `test_google_auth.py` (M11) — DONE: 20 tests cover code-exchange/link success, RSA JWK parsing, `at_hash` claim handling, invited users, unknown/unverified/deactivated rejection, signature/audience/issuer/expiry/nonce checks, duplicate identity/email drift, role/assignment preservation, M9 refresh/logout behavior, audit events and concurrent first-time linking.
- **MUST:** `test_idempotency.py` (M8) — retry with the same key + body replays the stored response (same resource id, no double-mutation, budget/stock unchanged); same key + different body/project → 409; a failed first attempt frees the key for a safe retry; concurrent same-key requests execute exactly once; keys are namespaced per user and per operation; invalid key lengths → 400.
- **MUST:** M9 token tests (rotation: old refresh invalid after use; revocation: logout kills server-side; deactivated user blocked on next use). *(DONE — `test_auth_sessions.py`: 23 tests incl. rotation, old/new-token behavior, logout + revoked + expired + deactivated + reactivation, reuse/theft family-revocation, auth events with IP, and two real-connection concurrency races — same-token refresh exactly-once, old-token reuse, refresh-vs-logout determinism)*

**Security considerations**
- Role-scope project responses per role; never leak `budget_*` to client. *(M6)*
- Idempotency-key validation (server-side key namespace per user). *(DONE — M8)*
- **M10:** lifecycle transitions admin-only + fully audited (actor, timestamp, old/new state). ARCHIVED projects are read-only for admins and invisible to others; never a DELETE endpoint. Project codes validated/format-enforced; uniqueness guaranteed.
- **M11:** Google is authentication only — ICE user record/role/assignments/permissions are the authorization source; **Google auth must never auto-grant ADMIN**. Validate OIDC `iss`/`aud`/`email_verified`, PKCE/nonce + state on callback; link by verified email only; deactivated users blocked; refresh rotation/revocation (M9) inherited; audit every auth event (login/refresh/logout/email-change). Account-linking risk is handled by authoritative `google_sub` lookup plus verified-email linking and 409 rejection when an identity/email is already bound elsewhere.
- Audit every finance and assignment write.
- Continue token work: **optional httpOnly-cookie transport** for the refresh token (deliberately deferred in M9 — dev is cross-origin and SameSite=None requires HTTPS; the rotation/revocation half of the Phase-1 security debt is now DONE).

**AI/ML considerations:** none required. But record **structured** cost data (cost codes, milestone events) — this becomes a future feature.

**Acceptance criteria**
- Two concurrent consumptions of the same item both persist; ledger sum equals `quantity_on_hand`.
- A supervisor/client blocked from projects after unassignment within one request.
- `Project.budget_spent` equals `SUM(job_costs)`; milestone completion creates the configured `%` invoice as draft. *(DONE — M4 + M5)*
- Client role cannot read any budget field; can read own invoices. *(DONE — M3 RBAC slice + M5 restricted shape)*
- No audit row missing `ip_address` — auth events now record it (Phase 3 M9); business mutations still pass NULL; refresh tokens rotate and deactivated users are cut off immediately. *(M9: refresh rotation/revocation/cutoff DONE)*
- **(M10)** Admin creates a project → gets a unique auto-generated code; project can be walked DRAFT→ACTIVE→COMPLETED→ARCHIVED and back (RESTORE) only via audited admin actions; ARCHIVED absent from normal project lists yet present in reporting; no project state can be hard-deleted; seed/demo projects exist only when a dev/demo flag is set.
- **(M11)** DONE: Sign-in with Google authenticates an existing or invited ICE user (role + project assignments unchanged), rejects unknown emails, never yields ADMIN, and uses rotating/revocable M9 sessions blocked for deactivated users.

---

## Phase 4 — Operational Control & Production Readiness

**Goal:** Everything can be deployed, monitored, backed up, and changed safely by one person (the operator). Also: background jobs for scheduled computation.

**Business value:** Low-to-medium direct value, but **gating**: without this, nothing above is safely usable with real money at risk.

**Features**
- **MUST:** CI/CD — GitHub Actions: lint (ruff + oxlint) + typecheck (mypy/tsc) + `pytest` + coverage gate + frontend build; PR/merge gates. *(P4.1 DONE: `.github/workflows/ci.yml` runs ruff/mypy/pytest incl. migration chain, `git diff --check`, frontend build + oxlint on every PR and push; pre-existing lint/type findings enforced via committed baselines + a delta gate. Coverage gate deferred to a later P4 milestone.)*
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
- A PR that fails ruff, mypy, tsc, or tests is blocked. *(P4.1: enforced on GitHub Actions with baseline-aware gates.)*
- Deploy is scripted end-to-end from empty Terraform state; secrets never in repo.
- Rate limit of 5/min holds per-user behind an LB with 4 workers.
- Backup restore verified in a controlled env; alerts fire on 5xx bursts.

---

## Phase 5 — Procurement & Multi-Location Inventory

**Goal:** The procurement pillar: purchase orders, delivery verification, and inventory spanning warehouse → transit → site with schedule-driven restocking.

**Status (Aug 14, 2026):** the first milestone (**M14 — Vendors + Purchase Orders**, the "vendor entity + PO entity + PO lifecycle + approval workflow" MUST/SHOULD items below) is DONE and test-pinned. **M15 — delivery verification/receiving — is IN PROGRESS** (schema + models + migration `l5d6e7f8a9b0` landed per `docs/M15_IMPLEMENTATION_PLAN.md`; receiving API/service, notifications, and frontend pending). The location dimension and the demand forecast are **NOT started** (M16). Vendor performance tracking (on-time %, price) is blocked on M15 delivery data.

**Business value:** High — this is where material spend is controlled; PO verification prevents paying for unverified goods; 3-location tracking reduces stockouts/misplacement across 15 sites.

**Features**
- **MUST:** Vendor entity (name/contact/payment terms) + vendor performance tracking (on-time %, price). — *vendor master data DONE (M14); performance tracking pending (needs M15 delivery data)*
- **MUST:** Purchase Order entity (vendor, lines, quantities, project, status) + PO lifecycle. — *DONE (M14)*
- **MUST:** Delivery verification — QR-code scan **or** photo-verified receipt against PO lines; verified receipt releases stock into inventory and triggers cost entries. — *IN PROGRESS (M15: schema/models landed; receiving API + job-cost/stock release pending)*
- **MUST:** Location dimension: `warehouse` / `transit` / `site` for inventory; transfers between locations recorded as movements. — *NOT STARTED (M16)*
- **MUST:** Low-stock **forecast** alerts using next-7-days-scheduled demand (from tasks + BOQ/BOM) rather than static thresholds. — *NOT STARTED (M16; needs a Phase 4 worker)*
- **SHOULD:** Approval workflow: Procurement creates PO → (optional) Admin approve → receive. — *approval workflow DONE (M14, mandatory — no auto-approve bypass)*
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
| **Phase 3** | Row-locked ledger; assignments API; project lifecycle+admin (M10); computed health; job costing + invoices; client role-scope; Google Sign-In (M11); refresh rotation + revocation | health-override UI; task cycle detection | — |
| **Phase 4** | CI/CD; IaC+deploy; secrets; logging/monitoring; backups; rate-limit fix; structured errors | worker + scheduled health; pagination/indexing | load test; npm audit/pip-audit |
| **Phase 5** | Vendors/POs; QR/photo verification; 3-location inventory; schedule-driven low-stock; upload-hardening | PO approvals; roll-up view | forecast from weather |
| **Phase 6** | Photo+voice capture; offline-first sync; hold-point gating; attendance/toolbox; mobile-first UI | notifications (vendor/stock) | — |
| **Phase 7** | Data pipeline; delay-risk with review trail; feature flags; model_runs audit | CV QC review queue | BOQ generation; portfolio forecast |
| **Phase 8** | — | — | multi-tenant, compliance, **SSO/OIDC beyond Google (M11 is the foundation)** |

**Implicit guardrail:** no phase ships to production without the Phase 4 observability + CI + backup rails. If budget forces a cut, preserve: **Phase 3 (integrity/finance + lifecycle + Google) → Phase 4 (production) → Phase 6 (field photos/offline) → Phase 7 (delay-risk)**; the procurement phase is the one most safe to trim/reorder.

**Sequencing guardrail (Aug 10):** within Phase 3, **M10 (Project Lifecycle & Admin) must precede M3 and M5**, and **M9 (token hardening) must precede M11 (Google Sign-In)**, which in turn must precede any real-user/client rollout. M6 must land before real clients authenticate on Google.
