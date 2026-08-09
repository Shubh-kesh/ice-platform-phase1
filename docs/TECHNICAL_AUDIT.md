# ICE Platform — Comprehensive Technical Audit

**Audit date:** August 9, 2026
**Scope:** Current repository state on branch `claude-development`
**Nature:** Analysis only. No source code modified.
**Evidence basis:** Direct source inspection, live database inspection, and verification runs below.

> **Key principle:** Source code is the single source of truth. Documentation claims were verified against code; several are stale and are called out in Part 6.

## Verified evidence (commands actually run)

| Check | Result |
|---|---|
| Backend tests | `33 passed` against real Postgres (`ice_test_db`) |
| Coverage | `73%` overall; lowest: inventory `39%`, projects `42%`, tasks `42%` |
| Backend lint (`ruff check app`) | **5 errors** (unused imports, F401) |
| Backend types (`mypy app`) | **10 errors** (forward-refs, config) |
| Frontend `tsc -b && vite build` | Clean build (~350 KB JS) |
| Frontend lint (`oxlint`) | 2 warnings (fast-refresh export) |
| Live DB | 11 tables, 2 Alembic migrations applied |
| Secret hygiene | `backend/.env`, `frontend/.env` gitignored (not tracked) |

---

## PART 1 — Project structure

```
repo root/
├── backend/                     FastAPI application (Python 3.12 target)
│   ├── app/
│   │   ├── main.py              App wiring: CORS, rate-limiter, middleware, /health
│   │   ├── api/
│   │   │   ├── deps.py          get_current_user, require_role (RBAC factory)
│   │   │   ├── project_access.py Shared project-visibility helpers
│   │   │   └── v1/              Routers: auth, users, projects, audit, tasks, site_logs, inventory
│   │   ├── core/                config, async engine, security (JWT/bcrypt), rate_limit
│   │   ├── middleware/audit.py  record_audit() helper (not a middleware)
│   │   ├── models/              SQLAlchemy ORM: user, project, task, site_log, inventory, finance, audit
│   │   ├── schemas/             Pydantic request/response contracts
│   │   └── seed.py              Demo data: 15 projects + 4 role users
│   ├── alembic/                 Migrations (2 revisions) + env.py
│   ├── tests/                   pytest suite (5 files, 33 tests)
│   ├── Dockerfile               multi-stage, non-root, gunicorn x 4 workers
│   ├── requirements*.txt        runtime + dev deps
│   ├── alembic.ini, pytest.ini
│   └── .env                     (gitignored, local-only)
├── frontend/                    React 19 + Vite + TanStack Query SPA
│   ├── src/lib/                 api.ts (axios + token refresh), auth-context
│   ├── src/pages/               Login, CommandCenter, ProjectDetail
│   ├── src/components/          AppShell, ProjectCard, KpiStrip, HealthDot, ProjectTimeline, DailySiteLogs, InventoryPanel, ProtectedRoute
│   └── src/types/               Shared TS contract types
├── docker-compose.yml           dev stack: postgres:16, redis:7, backend
├── docs/PRODUCT_REQUIREMENTS.md long-term product vision/reference
├── infra/terraform/             EMPTY — no IaC exists
├── .github/workflows/           EMPTY — no CI/CD exists
└── *.md / *.txt                 Root documentation (several stale — see Part 6)
```

**Duties**
- **Backend** = entire API + business logic + persistence. **No separate services/ or repositories/ layer** — business logic lives in route modules querying the ORM directly.
- **Frontend** = thin SPA over the JSON API; 3 routes, all data via TanStack Query.
- **Docker/compose** = local dev only. Postgres + Redis provisioned; **Redis is never used by any code**.
- **Root docs** = historical Phase 1/2 delivery notes, partly contradicted by code (e.g., they claim tests use in-memory SQLite; code uses real Postgres).

---

## PART 2 — Current architecture

```
React SPA (Vite, no SSR)
   │  axios -> /api/v1  (Bearer JWT access token in memory; refresh token in localStorage)
   v
FastAPI app (main.py)
   |- CORS (fixed origin list) -- slowapi rate limiter (in-memory, per-process)
   |- v1 routers (auth, users, projects, audit, tasks, site_logs, inventory)
   |     |- RBAC via deps.require_role / project_access.assert_can_view_project
   |     `- Business logic INLINE in handlers (no services layer)
   v
SQLAlchemy 2.0 async (asyncpg) --> PostgreSQL 16
   `- record_audit() writes AuditLog inside the same transaction as the mutation
```

**Capability inventory**

| Concern | Status |
|---|---|
| Authentication | JWT access (30m) + refresh (7d), bcrypt hashing, rate-limited login |
| Authorization | 4 roles + project-assignment scoping for supervisors/clients |
| Caching | **None** (Redis configured/unused; no API or query cache) |
| Queues / background | **None** (no Celery/RQ/scheduler; health-status computation explicitly "Phase 2+" and not built) |
| File storage | **None** (GCS config stubbed in config.py, never called; `photo_urls` always empty) |
| Notifications | **None** (no email/SMS/websocket; vendor notifications from schedule changes absent) |
| Integrations | **None** (QuickBooks/Xero: schema columns only) |
| Logging | stdout + per-request latency log + `X-Process-Time-Ms` header; **no request-id, no structured sink** |
| Monitoring/obs | **None** (no metrics, tracing, alerting) |

---

## PART 3 — Database

**Technology:** PostgreSQL 16, SQLAlchemy 2.0 async (asyncpg), Alembic, pool_size 10 / overflow 20.

**Schema (11 tables, 2 migrations)**

| Table | Purpose | Notes / problems |
|---|---|---|
| `users` | 4 roles, bcrypt, `is_active` | unique email index OK; no `last_login` |
| `projects` | status + 3 health enums + budget + dates | health indicators **manually settable**; `budget_spent` denormalized |
| `project_assignments` | user<->project grants | **NO unique (project_id, user_id)** — duplicate grants possible |
| `tasks` | flat Gantt bars; self-ref `depends_on_id`; `sort_order` | **no cascade re-scheduling**; dependency validated on create only |
| `daily_site_logs` | append-only field report; `photo_urls` JSONB | **no unique (project_id, log_date)** — multiple logs/day |
| `inventory_items` | per-project SKU + denormalized `quantity_on_hand` | **no unique (project_id, name)** — duplicate SKUs |
| `stock_movements` | immutable ledger, signed-qty convention | read-modify-write race (below) |
| `job_costs` / `invoices` | finance scaffold — **never referenced by any endpoint** | dead weight today |
| `audit_logs` | who/what/when + JSONB changes | `ip_address` **always NULL** (never passed); no index on table_name |

**Indexes:** PKs + FK indexes (tasks, site_logs, inventory, movements, job_costs, invoices) + unique email. Missing: audit_logs (table_name, created_at), stock_movements (created_at), unique project_assignments.

**Constraints:** No DB-level `CHECK` (`percent_complete` 0-100 is Pydantic-only). Native Postgres enums. FKs use CASCADE / SET NULL.

**Transactions:** mutations commit atomically with their audit row (good). **Inventory movements are a read-modify-write with no `SELECT ... FOR UPDATE`** — two concurrent requests can double-apply a consumption and lose an update.

**Soft deletion:** none anywhere.
**Audit mechanism:** application-level `record_audit()` (users, projects, tasks, site logs, inventory). Absent for login/refresh, finance (no endpoints), and anything written outside endpoints (`seed.py` bypasses it).

**Data-integrity problems**
1. Concurrent stock movements can lose updates (no row locking).
2. `Project.budget_spent` is manual state; nothing writes `job_costs`, so they can never be reconciled.
3. Task `PATCH` doesn't validate `start_date <= end_date` (create does) — malformed tasks possible.
4. Task dependency cycles/self-reference not prevented; date changes never shift dependents.
5. Duplicate assignments, duplicate inventory SKUs, multiple daily logs/day all possible.
6. No idempotency on POSTs — a retried "record movement" double-decrements stock.
7. `seed.py` writes demo rows outside the audit trail.

---

## PART 4 — API

Versioned under `/api/v1`. Auth on everything except `/auth/login`, `/auth/refresh`, `/health`.

| Domain | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me` |
| Users | `GET/POST /users`, `PATCH /users/{id}` — admin only |
| Projects | `GET/POST /projects`, `GET/PATCH /projects/{id}` |
| Audit | `GET /audit/logs?[table_name&action&limit&offset]` — admin only |
| Tasks | `GET/POST /projects/{id}/tasks`, `PATCH/DELETE /projects/{id}/tasks/{tid}` |
| Site logs | `GET/POST /projects/{id}/site-logs` |
| Inventory | `GET/POST /projects/{id}/inventory`, `PATCH /projects/{id}/inventory/{iid}`, `GET/POST /projects/{id}/inventory/{iid}/movements` |

**Common pattern:** injected `AsyncSession` + `User`; `require_role(...)` for writes; `assert_can_view_project` for read scoping; HTTPException (400/403/404); `record_audit()` in the same transaction; Pydantic response models.

**Inconsistent / problematic patterns**
1. **No project-assignment management API** — only `seed.py` creates assignments; users can never be assigned/removed via the system. RBAC is demo-only in practice.
2. Route shape inconsistency: `/audit/logs` vs flat `/users`, `/projects`.
3. Only audit has pagination (OFFSET/LIMIT over an **unindexed** `ORDER BY created_at DESC`).
4. `PATCH /projects` lets supervisors set health fields directly — command-center "health" is **typed, not computed**.
5. `depends_on_id` in `PATCH /tasks` isn't cycle-guarded; create validates same-project FKs only.
6. No idempotency keys; no ETag/optimistic-concurrency; last-write-wins everywhere.
7. Mutations return no structured errors to the UI beyond login (see Part 5).

---

## PART 5 — Frontend

- **Routing:** react-router-dom — `/login`, `/` (CommandCenter), `/projects/:projectId`; everything except `/login` behind `ProtectedRoute`.
- **State:** TanStack Query server cache (staleTime 30s, retry 1); local `useState` forms; `AuthContext` for identity + bootstrap refresh.
- **API integration:** axios with request interceptor (Bearer) and response interceptor (single-flight 401 -> refresh -> retry, fallback to `/login`). Access token in memory; refresh token in `localStorage`.
- **Auth:** silent bootstrap refresh on load; `logout` clears state but doesn't navigate.
- **Forms/validation:** hand-rolled, minimal client checks; server 422s surfaced only on Login.
- **Error/loading states:** spinners + error banner + retry on list queries; **none on mutations** — Task/SiteLog/Inventory mutations silently drop errors (only `recordMovement` uses `alert()`).
- **Mobile/responsive:** responsive grids on command center; but `AppShell` sidebar is a fixed `w-60` that never collapses — poor fit for the PRD's mobile-first field requirement.
- **Reuse:** HealthDot/ProjectCard/KpiStrip reused well; `formatCurrency`/`formatDate` duplicated; no error boundary; no test/RTL infra.

**Weaknesses**
1. Mutation error handling effectively missing -> silent data-entry failures on site.
2. `localStorage` refresh token is XSS-exposable.
3. No PWA/offline layer at all.
4. ProjectDetail shows **full budget figures to the CLIENT role** (PRD intends a view-only portal).
5. ProjectDetail fires 4 sequential queries (project, tasks, logs, inventory) — no `Promise.all`, no aggregate endpoint.

---

## PART 6 — Phase 1 and Phase 2 (source-derived, not doc-derived)

Git history: `a2dc696` (first commit — Phase 1), `733b90b` (critical fixes), `8b3979f` "phase2 in mid".

### Phase 1
**Completed**
- Auth: login, refresh, `/me`; JWT + bcrypt; rate-limited auth; password policy (8+/upper/digit).
- RBAC: 4 roles; admin-only user/project mutation; project-scoped visibility helper.
- Audit: `record_audit` on user & project CRUD + admin read endpoint.
- Projects CRUD + 3-color health fields; command-center UI (cards, KPI, drill-down); seed (4 users + 15 projects); auth/users/RBAC tests.

**Partially completed**
- Health indicators exist but are **manual** (no computation path).
- Docs (QUICK_START / PHASE2_READY / IMPLEMENTATION_SUMMARY) are **stale**: they claim in-memory SQLite + "15+ tests" and "production-ready / scale to thousands" — code uses real Postgres with 33 tests; readiness claims are aspirational.

**Missing**
- Project-assignment management API (seed-only today).
- Login/refresh audit events.

### Phase 2
**Completed**
- Tasks CRUD + basic Gantt bars (status/%) with correct RBAC.
- Daily site logs (append-only create/read) with RBAC.
- Inventory items + stock-movement ledger with negative-balance guard; admin/procurement write RBAC.
- Finance *schema* (`job_costs`, `invoices`); audit on all Phase 2 writes; shared `project_access`; tests for tasks/logs/inventory (33 total pass — verified).

**Partially completed**
- Gantt is flat; `depends_on_id` stored but **date changes do not shift downstream tasks** and there are **no vendor notifications** (PRD's "Dynamic Gantt" core is absent; the frontend never even sends `depends_on_id`).
- Low-stock is a `quantity_on_hand <= reorder_threshold` flag — no 7-day scheduled-demand threshold or alerts.

**Missing**
- Financial endpoints, milestone invoicing, cost roll-up, accounting sync (explicitly "scaffold only").
- Photo upload (`photo_urls` always []) and voice-to-text.
- Cross-project inventory roll-up (sidebar "Inventory" link is a disabled Phase-2 stub).
- QR/PO verification; 3-location (warehouse/transit/site) tracking (inventory is per-project only).
- Celery/background jobs (Redis unused).
- Quality & safety hold-points (entire pillar D absent).

---

## PART 7 — Requirements gap matrix

Reference: `docs/PRODUCT_REQUIREMENTS.md`.

| Requirement | Status | Evidence | Gap | Priority |
|---|---|---|---|---|
| 4-role RBAC (Admin/Supervisor/Procurement/Client) | IMPLEMENTED | `models/user.py`, `deps.require_role` | — | — |
| 4.1.1 Unified dashboard, color health, drill-down | IMPLEMENTED | `CommandCenter.tsx`, `ProjectCard`, `HealthDot` | health manual, not computed | Med |
| 4.1.2 Dynamic Gantt (cascade shifts + vendor notify) | PARTIALLY_IMPLEMENTED | `tasks` CRUD + bars | no auto-shift / notifications; dependency unused by UI | High |
| 4.1.3 Daily logs — 5 photos + voice-to-text | PARTIALLY_IMPLEMENTED | `DailySiteLogs.tsx`, `photo_urls` JSONB | no upload, no voice capture | High |
| 4.2.1 Stock across warehouse/transit/site | NOT_IMPLEMENTED | `inventory_items` per-project only | no location dimension | High |
| 4.2.2 Low-stock from 7-day scheduled demand | PARTIALLY_IMPLEMENTED | `InventoryPanel` reorder flag | static threshold, no schedule-driven alerts | Med |
| 4.2.3 Digital POs (QR/photo verification) | NOT_IMPLEMENTED | no PO entity | full feature absent | High |
| 4.3.1 Job costing tagged to cost codes | NOT_IMPLEMENTED | `job_costs` table only (no `cost_code`, no API) | full feature absent | High |
| 4.3.2 Milestone-based auto invoicing | NOT_IMPLEMENTED | `invoices` table only | full feature absent | Med |
| 4.3.3 QuickBooks/Xero/custom-ledger sync | NOT_IMPLEMENTED | `external_*` columns unused | blocked on OAuth-credentials decision | Med |
| 4.4.1 Hold-point inspections w/ photo evidence | NOT_IMPLEMENTED | nothing | full feature absent | High |
| 4.4.2 Safety attendance + toolbox talks | NOT_IMPLEMENTED | `workers_present` count only | full feature absent | Med |
| 5.1 CV QC (anomaly scan) | NOT_IMPLEMENTED | — | AI layer absent | Later |
| 5.2 Predictive delay (weather/vendor history) | NOT_IMPLEMENTED | — | AI layer absent | Later |
| 5.3 AI BOQ from drawings | NOT_IMPLEMENTED | — | AI layer absent | Later |
| 6.1 Offline-first field capture + sync | NOT_IMPLEMENTED | no PWA/offline code | full feature absent | High |
| 6.2 Audit trail (financial entries) | PARTIALLY_IMPLEMENTED | `audit_logs`, `record_audit` | no finance entries; `ip_address` never set; seed bypasses | Med |
| 6.3 Performance at 15 projects | UNCLEAR | default indexes, small data | unproven at scale | Low |
| 6.4 Security & privacy (client view-only) | PARTIALLY_IMPLEMENTED | client sees budgets | see Part 8 | Med |
| 6.5 Reliability | UNCLEAR | no backups/failover | single instance | Med |

---

## PART 8 — Security audit (risks only; nothing exploited)

1. **Refresh token in `localStorage`** (`api.ts:22-25`) — any XSS payload can read it; the access-token-in-memory choice is good, but the long-lived refresh key is the weakest link. **HIGH**
2. **Refresh tokens are un-rotated and server-side non-revocable** — `/auth/refresh` re-issues a pair forever; no session store, no revocation on logout (client-side only). **HIGH**
3. **Rate limiting is in-memory + per-process** under gunicorn `--workers 4` (`Dockerfile:46`): effective login cap ~20/min aggregate; and `get_remote_address` uses `request.client.host`, so behind a reverse proxy **every user shares one IP** — the limit can be exhausted globally (or bypassed via multiple proxies). **MEDIUM-HIGH**
4. **Client role sees project financials** (budget total/spent) via the standard project read when assigned. **MEDIUM**
5. **Password policy** is 8 chars + 1 upper + 1 digit; no length cap (bcrypt truncates at 72 bytes); no lowercase/special requirement. **LOW-MED**
6. **CSRF** not applicable (Bearer header auth + strict CORS allowlist). OK.
7. **SQL injection:** none found — all parameterized via SQLAlchemy. **LOW**
8. **XSS:** React auto-escapes; no `dangerouslySetInnerHTML`; photo URLs never rendered. Main vector remains #1. **MED** (via #1)
9. **File uploads:** none today; must be designed safely (type/size scan, GCS signed URLs) before any photo upload lands.
10. **Audit gaps:** no login/refresh events, no assignment audit (no API), no read audit; `ip_address` never recorded; audit rows immutable by convention only (no DB trigger/hardened permissions).
11. **UUID parsing:** `uuid.UUID(user_id)` in `deps.py:45` / `auth.py:55` can raise `ValueError` -> 500 on malformed-but-signed tokens. **LOW**
12. **Secrets:** `.env` gitignored (verified); `docker-compose.yml` hardcodes `SECRET_KEY: local-dev-secret-change-in-production` — must never reach prod; `seed.py` ships known demo credentials (documented, non-prod). **LOW**
13. **Tenant isolation:** within-endpoint visibility checks are applied consistently; the real gap is that assignments can't be managed via API.

---

## PART 9 — Performance

At the 10–15 project scale, most items are low-severity but will matter as data grows:

1. **Inventory lost-update race** under concurrent writes — correctness risk. **HIGH**
2. **Audit listing** — `ORDER BY created_at DESC` + `OFFSET` on an unindexed column. **MED**
3. **No caching** on hot reads (`/projects`, project bundles); every render hits Postgres; TanStack Query is the only mitigation. **MED**
4. **ProjectDetail fan-out** — 4 sequential queries per open (not N+1, but no `Promise.all`, no aggregate endpoint). **LOW**
5. **No N+1 patterns** in the route layer today (lists return scalars; no nested relationship loads).
6. **Payloads** — full-object lists (users, projects) with no projection/pagination. **LOW**
7. **Async throughout** (asyncpg + FastAPI async handlers), no blocking calls in hot paths. Good baseline.
8. **Redis provisioned but unused** — free headroom for a persistent rate limiter, caches, and queues.

---

## PART 10 — Testing

- **Backend (verified):** 33 tests, all pass against real Postgres. Cover auth, users, tasks, site logs, inventory + RBAC paths.
- **Frontend tests:** none (no vitest/RTL config or tests).
- **Coverage 73%:** worst areas — `inventory.py` 39%, `projects.py` 42%, `tasks.py` 42%.
- **Missing critical tests:**
  - `test_projects.py` was flagged in docs as "to add" and **never added** — project CRUD, PATCH RBAC (assigned-only supervisor), health-field updates, budget validation are untested.
  - Audit endpoint (`/audit/logs`) and its filters/pagination — untested.
  - Inventory: no client read-isolation test, no concurrent-movement race test, no ledger-reconciliation test.
  - No migration/model-drift test; no seed test; no finance tests (no endpoints yet).
- **Highest-risk untested areas:** finance, inventory ledger integrity under concurrency, project mutations, and any future feature until the suite is extended.

---

## PART 11 — Code quality

- **Duplication:** the "build `changes` dict from `model_dump(exclude_unset=True)`" pattern is copy-pasted in `users.py:79`, `projects.py:91`, `tasks.py:100`, `inventory.py:111`.
- **Dead code / unused deps:** `tenacity`, `redis` (Redis unused), `GCP_PROJECT_ID`/`GCS_BUCKET_NAME` stubs; `finance.py` models unreferenced.
- **Coupling/abstraction:** no services/repositories layer; handlers mix auth, validation, business logic, DB access, and audit in one function; finance scaffold has no endpoint (dangling abstraction).
- **Inconsistent patterns:** `_get_item_or_404` vs `get_project_or_404`; per-module `write_roles`; `ip_address` parameter exists but is never used.
- **Lint/type debt:** ruff 5 F401 errors; mypy 10 errors (broken `Mapped["Project"]` forward-refs in 4 models, config) — **not CI-gated anywhere**.
- **Module size:** none egregious (< ~210 lines/file).
- **Dependencies:** exact pins (good); `psycopg2-binary` (Alembic) + `asyncpg` (runtime) both present; `greenlet` pinned — fine.

---

## PART 12 — Production readiness

**Good:** multi-stage non-root Dockerfile with healthcheck; compose runs migrations on start; env-driven config; uniform 500 -> JSON error shape; request-latency logging.

**Not ready for production:**
1. No CI/CD — `.github/workflows/` is empty; nothing gates lint/type/test.
2. No IaC — `infra/terraform/` is empty; no Cloud Run/GKE manifests.
3. No secrets-manager integration; deploy-time secrets would be plain env vars.
4. No real observability: stdout logs only; no request-ids, metrics, tracing, alerting, dashboards.
5. No backup/DR strategy (single compose Postgres volume).
6. Rate limiter is in-memory/per-process — ineffective in production deployments (Part 8#3).
7. Migrations exist but prod application/bootstrapping is manual.
8. Docs claim "production-ready" — contradicted by the above; treat as aspiration.

---

## PART 13 — AI/ML readiness

Intended: (1) CV QC, (2) predictive delay, (3) drawing->BOQ.

**What supports ML today**
- `tasks` (start/end/status/%complete) — usable schedule history for basic delay signals.
- `stock_movements` — consumption patterns for materials demand modeling.
- `daily_site_logs` (free-text `weather`, `issues`) — weak, unstructured signal.
- `audit_logs.changes` (JSONB) — lightweight change history.

**Missing (data/enablement, not modeling)**
1. **Image pipeline absent** — CV QC needs deterministic photo hosting (GCS bucket config exists but no upload/serving/presigned-URL path) and stable photo IDs per site-log. **[blocking for 1]**
2. **Structured feature signals absent** — `weather` is free text; **no vendor entity** and no vendor-performance history, so delay-prediction inputs can't be assembled yet. **[blocking for 2]**
3. **No event/history backbone** — only `updated_at`; no delay-event log, milestone-invoice linkage, or per-SKU unit-cost history (needed for BOQ->cost).
4. **No async processing** — no queue/worker (Redis unused, no Celery/RQ); model serving and image pre-processing need one. **[blocking for all]**
5. **No model-result storage / audit-metadata plan** — PRD requires model-id, input snapshot, confidence, and human sign-off stored; nothing supports "AI output is non-authoritative until reviewed".
6. **No feature pipeline / offline replay** — ML datasets can't be reconstructed from the current schema.

**Recommendation:** Sequence AI after the data-collection backlog (structured weather/delays/vendors, GCS + preview, async worker, ML-audit rows). Most reachable first target is **predictive delay from task/vendor data** (schedule history closest to existing schema); CV QC is the farthest.

---

## PART 14 — Top architectural/technical risks (ranked)

| # | Severity | Problem | Evidence | Impact | Recommendation |
|---|---|---|---|---|---|
| 1 | CRITICAL | Inventory ledger lost-update on concurrent movements (no row lock) | `inventory.py:146-162` read-modify-write | stock silently wrong; downstream costing/PO wrong | `SELECT ... FOR UPDATE` + periodic ledger reconciliation |
| 2 | CRITICAL | Budget health is manual and `job_costs` never wired (finance scaffold-only) | `models/finance.py` unreferenced | command-center health is typed-in, not real | build job-costing + budget roll-up from ledger; auto-compute health |
| 3 | CRITICAL | No project-assignment API — RBAC is demo-only | assignments only in `seed.py:156-159` | can't onboard real users; access control not operational | assign/unassign endpoints + UI, still enforced by `assert_can_view_project` |
| 4 | HIGH | Dynamic Gantt core absent: no cascade reschedule, no vendor notification, dependency unused by UI | `tasks.py` PATCH has no cascade; FE never sends `depends_on_id` | schedule slips invisible; coordination promise unmet | dependency-driven date propagation + notification hook (defer real sending) |
| 5 | HIGH | Refresh token in localStorage; refresh non-revocable/un-rotated | `api.ts:6-9,22-25`; `auth.py:44-63` | session persistence via XSS; deactivated users keep sessions | rotate/revoke server-side; httpOnly cookie option; logout endpoint |
| 6 | HIGH | Rate limiting ineffective behind proxy / multi-worker | `rate_limit.py`; `main.py:59`; `Dockerfile:46` | brute-force protection undermined in prod | Redis-backed limiter keyed on forwarded client IP |
| 7 | HIGH | No offline-first, no photo upload, no voice capture | site-logs API has no upload; `photo_urls` always [] | field pillar unusable in poor signal | mobile capture + queue + GCS presigned upload + sync |
| 8 | HIGH | No PO / vendor / multi-location inventory model | inventory is per-project only | procurement pillar (PO verification, 3 locations) blocked at schema | add warehouse/transit/site location + vendor + PO entities |
| 9 | HIGH | No CI/CD, IaC, monitoring, or backups | empty `.github/workflows`, `infra/` | anything ships untested; no prod observability; data at risk | GitHub Actions gates + TF/Cloud Run + Secret Manager + managed backups |
| 10 | MEDIUM | Client role reads project financials | `ProjectRead` returned to assigned clients | privacy/cost exposure vs intended view-only portal | role-scoped project response contract |
| 11 | MEDIUM | Task PATCH skips date-order validation; dependency cycles possible | `schemas/task.py` validator on create only | malformed schedule data; cycles break future rescheduling | shared validator on update + cycle detection |
| 12 | MEDIUM | `Project.budget_spent` editable freehand; no linkage to a ledger | `projects.py` PATCH accepts it | budget figures diverge from actual costs | derive spend from job costs; make field read-only |
| 13 | MEDIUM | No pagination/index on audit log and list endpoints | `audit.py`; unindexed `ORDER BY created_at` | grows linearly; admin pages get slow | composite indexes; cursor pagination |
| 14 | MEDIUM | No idempotency on POSTs (movements, site logs) | `inventory.py` POST | network-retry double-post double-decrements stock | client-supplied idempotency keys |
| 15 | LOW | Stale/contradictory root documentation; lint & type debt un-gated | ruff 5 / mypy 10 errors; docs claim SQLite tests | misleading roadmap; defects slip through | fix lint/type; refresh docs; add CI gates |

---

## PART 15 — Recommended next phases

Prioritized by dependency, security, data integrity, architecture, business value, production readiness, then AI-readiness (not the original SRS order).

### Phase 3 — Integrity, RBAC operability, and the Finance pillar (do first)
1. Row-lock inventory movements (`SELECT ... FOR UPDATE`); add unique constraints (assignments, inventory `(project_id, name)`, `(project_id, log_date)`); task date/cycle validation on update; idempotency keys on POSTs.
2. **Project-assignment management** API + UI (unblocks real user onboarding and closes the #3 CRITICAL).
3. **Finance pillar**: `JobCost` + `Invoice` CRUD with cost codes, milestone-based auto-invoice rules, budget spent += job costs (making health real), client view-only invoice listing. Defer external-accounting sync until OAuth credentials exist (explicitly decision-gated).
4. Security hardening: rotate + revoke refresh tokens, optional httpOnly cookie, IP capture into audit, login-event audit, UUID parse guard, secret validation in prod config.
5. Frontend: surface mutation errors, parallelize ProjectDetail queries, hide financials from CLIENT.

### Phase 4 — Production readiness
1. CI/CD (GitHub Actions: lint + typecheck + `pytest` + coverage gate; frontend build + lint).
2. IaC + deploy (Terraform or Cloud Run YAML), Secret Manager, managed Postgres with PITR backups, structured logging (Cloud Logging) + request IDs + Sentry/similar, load test at 15-project scale.
3. Redis-backed rate limiter keyed on forwarded IP; verified under 4 workers.
4. Extend the test suite: `test_projects.py`, audit endpoint, inventory concurrency/reconciliation, migration-drift check.

### Phase 5 — Procurement & multi-location inventory
- Vendor + Purchase Order entities; QR-code / photo-verified PO delivery -> admission to cost; three-location tracking (warehouse / transit / site) with inter-location transfers; 7-day low-stock alerts derived from the schedule; cross-project inventory roll-up view for Procurement.

### Phase 6 — Field experience: quality/safety hold-points + offline
- Inspection checklists and hold-point sign-off with mandatory photo evidence and phase gating (`Task`/`Project` phase logic); toolbox talks + worker attendance; photo upload via GCS presigned URLs; mobile-first PWA with offline-first queue-and-sync (conflict rules).

### Phase 7+ — AI/ML (only after the data backbone exists)
- Start structured data collection now: structured weather, delay/vendor events, image storage, async worker (Redis already present).
- Sequence: **predictive delay** -> **CV QC anomaly flagging (human-reviewed)** -> **drawing-to-BOQ**; every model output stored with model-id/input/confidence and mandatory human sign-off before it becomes authoritative.

---

## FINAL OUTPUT

**A. Current architecture summary** — Single-service monolith: React 19 + Vite SPA (TanStack Query, axios) over a versioned FastAPI API; PostgreSQL 16 via async SQLAlchemy; JWT access (memory) + refresh (localStorage); 4-role RBAC with per-project assignment scoping; application-level audit trail; no queues, cache, file storage, notifications, integrations, monitoring, or CI/CD. Redis provisioned but unused. Business logic is inline in route handlers (no services layer). Finance is schema-only.

**B. Phase 1 status** — Auth, RBAC, projects CRUD, manual 3-health dashboard, seed, tests: complete. Manual (non-computed) health and stale docs: partial. Missing: assignment-management API, login audit.

**C. Phase 2 status** — Tasks/Gantt bars, daily logs, inventory ledger, finance scaffold, cross-cut audit, tests (33 pass, verified): complete. Dynamic-Gantt cascade + vendor notify, and schedule-driven low-stock: partial. Missing: finance endpoints/invoicing/sync, photos/voice, roll-up view, PO/QR, 3-location tracking, Celery, quality-safety pillar.

**D. Requirements gap analysis** — 9 requirements IMPLEMENTED or PARTIAL; the financial (4.3), procurement (4.2.3), quality/safety (4.4), offline (6.1), and all AI (5.x) pillars are NOT_IMPLEMENTED. See Part 7 matrix.

**E. Top technical risks** — 3 CRITICAL: (1) inventory concurrency lost-update, (2) manual budget health / un-wired finance, (3) seed-only project assignments. 9 HIGH. See Part 14.

**F. Technical debt** — duplicated audit-pattern code; dead config (`redis`, `tenacity`, GCS stubs) and unreferenced finance models; no services layer; copy-paste validation gaps; ruff 5 + mypy 10 errors un-gated; stale docs.

**G. Production readiness** — NOT READY. Docker/compose hygiene is good; CI/CD, IaC, secrets, observability, backups, working rate limit, and managed migrations are all absent.

**H. AI/ML readiness** — NOT READY. No image pipeline, no structured weather/vendor/delay features, no async worker, no model-result storage. Tasks + stock-movement history are the only usable seeds. Sequence predictive-delay -> CV QC -> BOQ after data-collection work.

**I. Recommended Phase 3** — Data-integrity hardening + role-operable RBAC + the Finance pillar (job costing / milestone invoicing / budget roll-up) + token-security fixes + frontend error/release work. It closes the 3 CRITICAL risks and delivers the largest remaining business value.

**J. Recommended overall roadmap** — Phase 3 (integrity + finance + assignment API) -> Phase 4 (production hardening) -> Phase 5 (procurement: POs, 3-location inventory, demand alerts) -> Phase 6 (offline-first mobile + quality/safety hold-points) -> Phase 7+ (AI/ML layer).