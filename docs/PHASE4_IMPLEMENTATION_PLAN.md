# Phase 4 — Operational Control & Production Readiness

**Status:** PLANNED (not implemented). No code, migrations, or commits created.
**Date:** Aug 12, 2026.
**Basis:** Repository inspection at Phase 3 completion — M11 committed as
`4be655f` (migration head `i7d8e9f0a1b2`), Phase 3 verified (`89bad2d`),
working tree clean on `claude-development`. Source code is ground truth;
`docs/ROADMAP.md` Phase 4 section is the primary scope source.

This is the **plan**. The post-implementation record belongs in
`docs/PHASE4_IMPLEMENTATION_REVIEW.md` (created after work, never mixed with
planned behavior).

---

## 1. Objective

Make the ICE platform safely deployable, operable, monitored, backed up, and
changeable by one operator, with real users and real money at risk. Concretely:

- Every change is gated by CI (lint, types, tests, build) before merge.
- Production runs on managed infrastructure with managed PostgreSQL and Redis,
  deployed from code (IaC), with no secrets in the repository.
- The application is observable: structured logs with request IDs, error
  tracking, health/readiness, and alerting.
- Data is backed up and restore is drilled.
- Auth and API surfaces are production-hardened (rate limiting, TLS, headers,
  dependency/container scanning).
- A staging/UAT environment and an explicit GO/NO-GO gate exist before
  real-user rollout.

Phase 4 delivers no new end-user feature work; it is the production rail for
everything built in Phases 1–3.

## 2. Current State

### Repository

- Branch `claude-development`; working tree clean.
- Backend: FastAPI, async SQLAlchemy + asyncpg, Alembic chain head
  `i7d8e9f0a1b2`, bcrypt + JWT + M9 opaque refresh sessions, M11 Google
  Sign-In (Authorization Code + PKCE, server-side ID-token verification).
- Frontend: React 19 + Vite SPA, TanStack Query, no test framework.
- Docker Compose dev stack: `postgres:16-alpine`, `redis:7-alpine`, backend
  multi-stage non-root Dockerfile (gunicorn ×4 uvicorn workers, `/health`,
  migrations + demo seed on entrypoint).
- Test baseline: 213 backend tests pass; frontend build clean; frontend lint 1
  pre-existing warning; Ruff 2 pre-existing F401 errors; mypy 10 pre-existing
  errors; coverage ~75%.

### Gaps (verified)

- `.github/workflows/` — empty (no CI).
- `infra/terraform/` — empty (no IaC).
- Secrets live in `backend/.env` / `frontend/.env` (gitignored) and Compose
  `environment` blocks; Compose hardcodes `SECRET_KEY: local-dev-secret-...`.
- Rate limiting is slowapi **in-memory per-process** — ineffective under
  4 workers / behind a proxy.
- Logging is human-oriented line logs (latency middleware only); no request
  IDs, no JSON, no error tracking, no metrics, no alerting.
- No backups or restore runbook.
- Dev Compose exposes PostgreSQL/Redis on host ports and bind-mounts `app/`
  with `uvicorn --reload`; no production Compose variant exists.
- Refresh token is stored in `localStorage` (M9-deferred httpOnly cookie);
  Google callback uses synchronous `httpx` inside async handlers; admin
  self/last-admin deactivation is unguarded.

## 3. Phase 4 Scope

From `docs/ROADMAP.md` Phase 4 (MUST/SHOULD/NICE TO HAVE) plus verified gaps:

**MUST (P0-gating):**
- CI/CD on GitHub Actions: ruff, oxlint, mypy, tsc, `pytest`, coverage gate,
  frontend build, migration-chain test, `git diff --check`; PR/merge gates.
- IaC + deploy for backend, managed PostgreSQL, Redis, and secrets.
- Secrets management (secret manager) — no secrets in compose/env files.
- Structured logging (request IDs, JSON), error tracking, uptime + latency
  alerting.
- Backups — managed Postgres PITR + point-in-time restore runbook.
- Rate limiting fixed: Redis-backed limiter keyed on forwarded client IP,
  validated under 4+ workers.

**SHOULD:**
- Lightweight background job runner for health recomputation / stale cleanup.
- Staging/UAT environment and production readiness gate.
- Playwright smoke (login → command center → project detail) in CI.

**NICE TO HAVE:**
- Load test at the 15-project profile; pagination/indexes on list endpoints.

## 4. Explicit Non-Scope

- No new user-facing features, no new Phase 5/6 functionality (procurement,
  photos, offline).
- No AI/ML work.
- No multi-tenant model, no compliance reporting, no SSO beyond Google
  (Phase 8).
- No database schema/migration changes unless a specific ops-driven index is
  approved (the migration strategy in §10 governs any such change).
- No event sourcing, no architecture rewrite.
- Not silently absorbing general technical debt (see §18 Risks and the
  ROADMAP/CURRENT_STATE debt lists) — each debt item is triaged as
  in-scope, deferred, or owner-decision.

## 5. Milestone Breakdown

Milestones are independently verifiable; each has its own review document.

### P4.1 — CI/CD & Automated Quality Gates

- **Objective:** every PR and main-branch push is gated on lint, types, tests,
  migration integrity, and build; failures block merge.
- **Scope:** GitHub Actions workflows; backend job (ruff, mypy, pytest incl.
  migration test against a service Postgres, coverage), frontend job (tsc
  build, oxlint), `git diff --check`, dependency/security scan stubs; PR gate
  + main gate; caching; artifact/report upload; baseline-debt policy.
- **Non-scope:** deploy automation (P4.2), secret provisioning (P4.3).
- **Dependencies:** none outside CI secrets (a test-only Postgres on the runner
  or GitHub-hosted service container).
- **Files likely affected:** `.github/workflows/ci.yml` (+ `cd.yml` later),
  `backend/requirements-dev.txt`, `frontend/package.json` (test script when
  added), possibly `pytest.ini`/mypy/ruff config for CI-only settings.
- **Infrastructure impact:** CI runner only.
- **Database impact:** ephemeral Postgres for migration replay; no prod impact.
- **API/Frontend impact:** none.
- **Security impact:** enforces change hygiene; secret scan option.
- **Testing strategy:** CI itself is the test; add a "boot in prod-like
  config" smoke job.
- **Rollback strategy:** revert workflow file; gates removed on merge revert.
- **Acceptance criteria:** a deliberately failing change (e.g., a lint error, a
  failing test) is blocked; a passing PR merges; migration head verified in CI.
- **Quality gates:** ruff (baseline-aware), mypy (baseline-aware), pytest
  (213+), coverage gate, `git diff --check`, tsc build, oxlint.
- **Documentation:** this plan + `docs/P4.1_IMPLEMENTATION_REVIEW.md`.

**Baseline-debt policy (important):** Ruff currently has 2 pre-existing F401
errors and mypy 10 pre-existing errors; the frontend has 1 pre-existing oxlint
warning. CI must distinguish **baseline** from **newly introduced** errors:
  - Recommended approach: a CI step that asserts error counts/diffs equal the
    committed baseline (e.g., `ruff check ... | wc -l` compared to a checked-in
    threshold, or `mypy` "new errors only" diff). Do **not** fix baseline debt
    inside P4.1 unless approved — it is triaged separately (P2 hardening).
  - New errors in any PR must fail the gate.

### P4.2 — Production Infrastructure & IaC

- **Objective:** reproducible production/staging infrastructure from code, with
  managed PostgreSQL and Redis, HTTPS edge, and zero host-ported dev services.
- **Scope:** Terraform (or Cloud Run YAML — owner decision) for backend
  service, managed PostgreSQL, managed Redis, networking/egress, volumes,
  migrations-as-deploy-step, environment separation (staging/production),
  resource limits, restart/health/readiness; a production Compose variant for
  the operator who does not use the cloud target.
- **Non-scope:** secrets content (P4.3), deploy pipeline wiring (P4.1/P4.2
  handoff), per-env DNS beyond one production domain + staging subdomain.
- **Dependencies:** P4.3 secrets must exist for the target env; provider choice
  (owner decision).
- **Provider signal (from repository):** the Dockerfile/`main.py`/config
  reference Cloud Run (`$PORT`), GCP load balancer health checks, and
  `GCP_PROJECT_ID`/`GCS_BUCKET_NAME` config stubs — GCP is the implied target,
  but **provider confirmation is an owner decision** (§19).
- **Files likely affected:** `infra/terraform/*` (new), `docker-compose.yml`
  (split dev/prod), `backend/Dockerfile` (non-root, distroless-friendly, no
  `--reload`), `backend/entrypoint.sh` (migration ownership, §10), optional
  `frontend` container + nginx/static host config.
- **Infrastructure impact:** managed DB/Redis/services created; dev Compose
  unchanged.
- **Database impact:** migration execution at deploy (see §10).
- **API/Frontend impact:** env-based `VITE_API_URL`; CORS origin list per env.
- **Security impact:** network isolation, managed service least privilege, TLS
  at edge, non-root container, resource limits.
- **Testing strategy:** empty-state `terraform apply` bootstrap drill;
  backend-boots-in-prod-config smoke; staging deploy.
- **Rollback strategy:** `terraform destroy`/pinned state + prior image
  rollback; DB rollback policy in §10.
- **Acceptance criteria:** deploy scripted end-to-end from empty Terraform
  state; no secrets in repo; staging and production separated; /health and
  readiness green behind TLS.
- **Quality gates:** `terraform plan` clean in CI, `terraform apply` on merge
  to main (env-scoped), container image build + scan, boot smoke.
- **Documentation:** `docs/P4.2_IMPLEMENTATION_REVIEW.md`.

### P4.3 — Secrets & Environment Management

- **Objective:** no secrets in code, env files, Compose, or CI logs; per-env
  configuration via a secret manager.
- **Scope:** inventory every variable; move production values to the chosen
  secret manager; wire retrieval at deploy/runtime; define required-vs-optional
  variables and validation (fail-fast on missing production values); remove
  dev-only hardcoded defaults from production paths (e.g., Compose
  `SECRET_KEY`); redaction policy in logs (§11).
- **Non-scope:** secrets already safe; no new variables.
- **Dependencies:** provider + secret manager choice (owner decision).
- **Files likely affected:** backend `app/core/config.py` (secret-manager
  source), `docker-compose.yml`, IaC, `.env.example` files, CI workflow
  secrets.
- **Infrastructure impact:** secret store created; runtime reads change.
- **Security impact:** core of Phase 4 — no credentials at rest in the repo;
  rotation runbook.
- **Testing strategy:** a CI/env check that fails if any secret placeholder or
  hardcoded default is present in a production configuration; local dev uses
  `.env` only.
- **Rollback strategy:** secrets are additive; rotation runbook covers rollback.
- **Acceptance criteria:** `git grep` finds no production secrets; app boots in
  prod with secrets from the manager only; rotation documented.
- **Quality gates:** secret-scan in CI; config-validation smoke.
- **Documentation:** `docs/P4.3_IMPLEMENTATION_REVIEW.md` + rotation runbook.

### P4.4 — Observability, Logging & Reliability

- **Objective:** structured, correlatable, redacted logs; error tracking;
  health/readiness; alerts; and the Redis-backed rate limiter.
- **Scope:** `X-Request-ID` middleware + correlation into logs; JSON structured
  logging (Cloud Logging or equivalent); error tracking (Sentry or equivalent);
  `/health` (liveness) + `/ready` (DB + Redis checks); metric-friendly spans
  where justified; alerting on 5xx bursts, uptime, latency; **log redaction**
  (Authorization header, passwords, refresh tokens, Google codes/ID tokens,
  client secret — never logged anywhere); migrate slowapi limiter storage to
  Redis keyed on forwarded client IP; add the worker/job runner (ROADMAP
  SHOULD) for health recomputation + stale cleanup.
- **Non-scope:** full tracing/monitoring platform; dashboards beyond core
  alerts.
- **Dependencies:** provider choices (logging/monitoring), Redis already
  provisioned.
- **Files likely affected:** `backend/app/main.py` (middleware, /ready),
  `backend/app/core/rate_limit.py`, `backend/app/core/config.py`, new
  `backend/app/services/` or `workers/` for jobs, `backend/requirements.txt`
  (e.g., `sentry-sdk`), IaC for alert config.
- **Database impact:** none (job runner reads existing tables).
- **API impact:** `/ready` endpoint; `X-Request-ID` on all responses; rate
  limits become distributed (behavioral change under multi-worker — must keep
  login 5/min, refresh 10/min, logout 10/min, Google 10/min semantics per
  real client IP).
- **Frontend impact:** none.
- **Security impact:** redaction is mandatory; never log credentials/tokens.
- **Testing strategy:** rate-limiter integration test simulating proxy headers
  + multiple workers (ROADMAP MUST); redaction unit test; readiness check test.
- **Rollback strategy:** feature-flag rate-limiter backend; logging is additive.
- **Acceptance criteria:** request IDs present and correlated; 5xx alerts fire
  in a controlled test; per-user 5/min login limit holds behind a proxy with
  4 workers; redaction verified by test.
- **Quality gates:** tests green; alert test passes; no credential leakage in
  sampled logs.
- **Documentation:** `docs/P4.4_IMPLEMENTATION_REVIEW.md`.

### P4.5 — Production Security Hardening

- **Objective:** close the Phase 1–3 documented security gaps that gate
  production and harden the surfaces for real users.
- **Scope (evaluate each, implement where gating):**
  - HTTPS/TLS at edge + HSTS + security headers (CSP, X-Frame-Options, etc.).
  - CORS restricted to the production origin.
  - httpOnly refresh-cookie migration — **owner decision** (§19); document
    transport/CSRF impact if adopted, keep localStorage otherwise with
    rotation mitigation.
  - Admin self-deactivation / last-admin protection (app change, M11-residual).
  - Synchronous `httpx` in async Google handlers → `AsyncClient` (P2 hardening).
  - Redis-backed rate limiting (carried from P4.4) + brute-force posture.
  - Dependency audit (`pip-audit` / `npm audit`) + container image scan in CI.
  - Google OAuth production configuration checklist (redirect URI, hosted
    domain, consent screen, client types) — configuration, not code.
  - Database least privilege + network isolation; backup encryption.
- **Non-scope:** new auth protocols (SSO beyond Google is Phase 8).
- **Dependencies:** P4.1 (scanning in CI), P4.2/P4.3 (env + secrets).
- **Files likely affected:** `backend/app/core/security.py`,
  `backend/app/api/v1/auth.py` + `users.py` (self/last-admin guard,
  AsyncClient), `frontend/src/lib/api.ts` (cookie vs storage transport if
  adopted), nginx/IaC headers, CI scan steps.
- **Infrastructure/Database/API/Frontend impact:** per-item; the httpOnly
  migration touches the token transport and frontend storage if adopted.
- **Security impact:** primary Phase 4 security milestone.
- **Testing strategy:** add tests for the last-admin guard, AsyncClient path,
  redaction, rate limits; Playwright smoke covers login flows.
- **Rollback strategy:** app changes are small and revertible; header/TLS
  changes revert via IaC.
- **Acceptance criteria:** TLS+HSTS live; no secrets/creds in logs; last-admin
  cannot deactivate the final active admin; container/dependency scan clean (or
  documented exceptions); Google OAuth prod checklist complete.
- **Quality gates:** CI scans, security tests, Playwright smoke.
- **Documentation:** `docs/P4.5_IMPLEMENTATION_REVIEW.md` + security notes.

### P4.6 — Staging/UAT & Production Readiness Gate

- **Objective:** a staging/UAT environment mirroring production, a full
  production-readiness checklist, a backup/restore drill, and an explicit
  GO/NO-GO gate before real users.
- **Scope:** staging env via IaC; runbook for deploy/rollback/migration;
  restore-from-backup drill (scripted); the §14 go-live checklist executed and
  signed; E2E Playwright smoke in staging and post-deploy.
- **Non-scope:** business sign-off beyond the documented checklist.
- **Dependencies:** P4.1–P4.5.
- **Files likely affected:** IaC env modules, runbooks, `docs/` go-live record.
- **Acceptance criteria:** staging fully functional (password + Google login
  with a provisioned ICE user, all business flows); restore drill succeeds;
  GO/NO-GO checklist all green.
- **Quality gates:** full CI + staging smoke + backup drill.
- **Documentation:** `docs/P4.6_IMPLEMENTATION_REVIEW.md` + go-live record.

## 6. Dependencies

- P4.1 and P4.3 are prerequisites for everything else (gates + no secrets).
- P4.2 depends on provider/secrets decisions.
- P4.4 depends on Redis (provisioned) and provider choices.
- P4.5 depends on P4.1 (scans), P4.2/P4.3 (env, TLS), and the httpOnly owner
  decision.
- P4.6 depends on P4.1–P4.5.
- General: Phase 3 must remain green (213 tests) throughout; no behavior
  regression to M9/M11 auth.

## 7. Infrastructure Architecture

Current: single dev Compose stack (Postgres + Redis + backend on host ports,
bind-mounted, `--reload`).

Target (production):

```
Internet
  └─ HTTPS (managed TLS, HSTS)
       └─ Frontend (static hosting / container + nginx)      [origin CORS]
            └─ /api/v1 -> Backend service (gunicorn ×N uvicorn, non-root)
                 ├─ Managed PostgreSQL (PITR, private network)
                 └─ Managed Redis (rate limits, future jobs)
  └─ Operator -> IaC (terraform) + CI/CD (GitHub Actions) + Secret Manager
```

Environment separation: `dev` (current Compose), `staging` (IaC mirror, shared
with UAT), `production` (IaC, restricted). Staging and production never expose
Postgres/Redis to the host. Migrations run as an explicit deploy step owned by
the pipeline (or entrypoint for the Compose operator variant), never in the
dev `--reload` path.

Provider: **GCP/Cloud Run is implied** by repository signals (Dockerfile
`$PORT`/Cloud Run comment, `main.py` GCP LB/Cloud Run health-check comment,
`GCP_PROJECT_ID`/`GCS_BUCKET_NAME` config stubs). Confirm as an owner decision
(§19). Terraform is the ROADMAP-preferred IaC.

## 8. CI/CD Strategy

**Workflows (GitHub Actions):**

1. `ci.yml` — on PR to `claude-development`/main and on push to main:
   - Job `backend`: services `postgres:16` (for real-DB tests + migration
     replay) → `pip install -r requirements-dev.txt` → `ruff check` →
     `mypy app` → `pytest tests/ -q` → `pytest tests/test_migrations.py`
     (fresh upgrade/downgrade/replay against the service DB) →
     coverage gate → `git diff --check`.
   - Job `frontend`: `npm ci` → `npm run build` (tsc + vite) → `npm run lint`.
   - Job `security`: `pip-audit` + `npm audit` (failing on known-vulnerable
     direct deps with a documented-exceptions allowlist) + optional
     Gitleaks/secret scan.
   - Job `infra`: `terraform plan` for changed envs (needs credentials only on
     main apply, plan uses read-only creds).
2. `cd.yml` — on merge to main (or a tag): apply IaC (staging), deploy backend
   image, run migrations, boot smoke (`/health`, `/ready`), then production
   apply (gated, manual or auto per owner decision).

**Failure behavior:** PR gate fails the merge; main deploy halts on any step
failure; no force-pass on the debt baseline.

**Caching:** pip cache, npm cache, `.mypy_cache`/`.ruff_cache`, Terraform
plugin cache; invalidate on lockfile change.

**Artifacts/reports:** pytest XML, coverage HTML, ruff/mypy summaries, npm
build output — uploaded on failure for fast triage.

**Baseline policy:** baseline debt (ruff 2, mypy 10, oxlint 1) is asserted as a
committed baseline; PRs must not increase it. Fixing debt is P2 hardening, not
a CI blocker.

## 9. Secrets Strategy

Inventory (current):

| Variable | Current home | Must move to secret manager |
|---|---|---|
| `SECRET_KEY` | Compose hardcoded `local-dev-secret-...` | Yes (production; per-env) |
| `POSTGRES_*` | `backend/.env`, Compose | Yes (production DB creds) |
| `GOOGLE_CLIENT_ID` | `backend/.env` | Yes (production value) |
| `GOOGLE_CLIENT_SECRET` | `backend/.env` | Yes (production value) |
| `GOOGLE_REDIRECT_URI` | Compose/env | Config, not secret (per-env) |
| `GOOGLE_HOSTED_DOMAIN` | Compose/env | Config |
| `REDIS_*` | Compose | Managed Redis creds → secret manager |
| `BACKEND_CORS_ORIGINS` | Compose | Config |
| `VITE_API_URL` | `frontend/.env` | Build-time config (public, not secret) |
| `GCP_PROJECT_ID`/`GCS_BUCKET_NAME` | config stubs | Config |

Principles: no secrets in git (`.gitignore` already covers `.env*`, `*.pem`,
service-account keys); dev uses `.env` files; staging/production read from the
secret manager at deploy/runtime; missing required production vars fail fast;
rotation runbook ships in P4.3.

## 10. Database / Migration Strategy

Current chain head: `i7d8e9f0a1b2` (through M11). Chain is replayable and
downgrade-safe for the tested paths (M11 downgrade is destructive for
Google-only rows — documented).

Phase 4 production migration strategy:

- **Ordering:** backup → pre-flight (connectivity, head check, free disk) →
  apply pending migrations explicitly as a deploy step → verify `alembic
  current` matches expected head → start new app revision → post-deploy smoke.
- **Pre-deployment checks:** migration test runs in CI against a scratch DB
  (upgrade → downgrade → upgrade replay); schema drift check.
- **Backup requirements:** managed Postgres PITR enabled before first
  production deploy; a full backup taken immediately before any schema change.
- **Upgrade verification:** `alembic current` + health/readiness after deploy.
- **Rollback strategy:** application rollback = deploy previous image (new
  migrations stay applied — backwards-compatible rule: any migration that would
  break the previous app revision must be split or flagged). For destructive
  migrations, the downgrade guard (as in M11) must be documented and the
  upgrade made in a forward-only, verified sequence.
- **Downgrade policy:** downgrades are developer/ops tools, exercised in CI for
  the chain; in production, prefer forward-fix over downgrade unless a
  non-destructive path exists.
- **Handling destructive migrations:** require explicit approval, a pre-merge
  plan, backup verification, and a documented NO-GO fallback (e.g., M11's
  `hashed_password NOT NULL` restore which fails while Google-only rows exist).
- **Production migration ownership:** the deploy pipeline owns `alembic
  upgrade head` (explicit step), or the entrypoint for the Compose-operator
  variant; a single owner is named per deploy.
- **Startup vs explicit:** production uses explicit pipeline-run migrations
  (startup runs them only in the Compose operator variant); dev keeps startup
  migrations.

No Phase 4 migration is planned unless an ops-driven index is approved (e.g.,
`audit_logs` list index) — and it would be its own reviewed milestone.

## 11. Observability Strategy

- **Request IDs:** middleware generates/accepts `X-Request-ID`, propagates it
  through response headers and log records.
- **Structured logging:** JSON records (timestamp, level, logger, request_id,
  method, path, status, latency, env) via `python-json-logger` or the chosen
  cloud logging agent; move the existing latency middleware to emit the same
  fields.
- **Error tracking:** Sentry (or equivalent) SDK with `release` set from the
  image tag; environment-tagged.
- **Health/readiness:** keep `/health` (liveness); add `/ready` checking
  database and Redis connectivity; wire both to LB/Cloud Run probes.
- **Metrics:** request rate/5xx/latency where the platform provides them;
  alerting on 5xx bursts, uptime, p95 latency.
- **Redaction (mandatory):** never log `Authorization` headers, passwords,
  refresh/access tokens, Google authorization codes, Google ID tokens, the
  client secret, PKCE verifiers, or full `state`/`nonce`. The Google auth
  paths already collapse failures to generic errors and log no credentials —
  preserve that; add a redaction test.
- **Auth-failure visibility:** safe counters/events for login, refresh, Google
  callback, and rate-limit rejections (stage + status only, no credentials).
- **Audit-log monitoring:** alert on `link_conflict`/reuse-detection events
  where meaningful.

## 12. Security Hardening

Carried into Phase 4 (evaluated per item, owner decisions where noted):

- HTTPS + HSTS + security headers (CSP, X-Frame-Options, Referrer-Policy,
  X-Content-Type-Options) at the edge.
- CORS allowlist per environment (never `*` with credentials).
- Redis-backed distributed rate limiting (login/refresh/logout/Google), keyed
  on forwarded client IP (trusted-proxy parsing).
- Brute-force posture: existing 5/10/10/10 per-minute limits preserved under
  multi-worker.
- httpOnly refresh-cookie migration — **owner decision** (§19); if adopted,
  document CSRF (SameSite) and the transport change; otherwise retain
  localStorage with rotation/revocation mitigation.
- Admin self-deactivation and **last-admin** protection (app change).
- Async Google HTTP (replace sync `httpx.Client` with `AsyncClient`).
- Dependency audits (`pip-audit`, `npm audit`) + container image scan in CI;
  documented-exception allowlist.
- Google OAuth production checklist: exact redirect URI, hosted-domain lock
  (recommended), consent-screen review, client type confirmation.
- Database least privilege + private network; encrypted backups.
- Docker/container: non-root (already), no debug tooling, pinned base images,
  resource limits, no host port exposure in production.

## 13. Staging/UAT Strategy

- Staging mirrors production topology (IaC module, same image, same env shape,
  smaller resources) with its own secret-manager namespace.
- UAT runs on staging with seeded non-production data (ICE_SEED_DEMO gated).
- Every release candidate deploys to staging first; Playwright smoke (login →
  command center → project detail) and the §14 checklist run there.
- Staging is the rollback rehearsal surface for deploy and migration.

## 14. Production Go-Live Gate

Explicit GO/NO-GO checklist. All items must be green (or explicitly waived by
the owner) before real users:

**Authentication**
- Password login works in production.
- Google login works with a provisioned ICE user (Google-only invite + link).
- Refresh rotation works (old token rejected after rotation).
- Logout revokes the family; revoked tokens fail refresh.
- Deactivated user is blocked at login and cut off at refresh.
- RBAC (admin/procurement/supervisor/client) verified per role.

**Business flows (smoke in staging + post-deploy)**
- Projects: create (codegen), lifecycle activate/complete/archive/restore.
- Assignments assign/unassign + isolation.
- Site logs create/read; inventory items + movements + reconciliation.
- Job costs + budget roll-up; billing milestones + invoice issue/pay/cancel.
- Audit logs readable by admin.

**Infrastructure**
- Migration applied to expected head; `/health` + `/ready` green.
- Backup taken; restore-from-backup drill passed.
- Deploy + rollback rehearsed on staging.
- Redis reachable and rate limiting distributed.

**Security**
- Secrets only from secret manager; TLS + HSTS live; CORS = production origin.
- Dependency/container scans clean (or documented exceptions).
- Google OAuth production config verified; no credentials in logs.

**Quality**
- CI green (ruff baseline, mypy baseline, 213 tests, migration tests,
  coverage gate, build, lint).
- Concurrency tests pass; Playwright smoke pass; boot-in-prod-config smoke pass.

**GO:** all green → flip DNS/production traffic on a gated deploy.
**NO-GO:** any MUST item red; revisit and re-run the gate.

## 15. Rollback Strategy

- **Application:** previous image tag; deploy pipeline keeps last-N images;
  health gate blocks promotion.
- **Database:** PITR restore runbook (drilled in staging); migrations are
  forward-only in production by policy with destructive-migration guardrails
  (§10).
- **Config/secrets:** additive secret changes; per-env override.
- **IaC:** state pinned/versioned, `terraform destroy` rehearsed in staging;
  change via plan/review.
- **Rate limiting/logging:** feature-flagged backends so a misconfigured
  limiter or logging change can be reverted without a full deploy.

## 16. Testing Strategy

- **CI unit/integration:** existing 213 tests + new Phase 4 tests (readiness
  endpoint, rate-limiter-under-proxy/multi-worker, log redaction, last-admin
  guard, async Google path, migration chain replay).
- **Migration tests:** scratch-DB upgrade/downgrade/replay in CI.
- **Concurrency:** existing real-connection races remain; add rate-limiter
  race semantics.
- **Boot smoke:** backend boots with prod-like config (no `.env` fallbacks) and
  reports `/health` + `/ready`.
- **E2E:** Playwright (login → command center → project detail; password +
  Google with provisioned ICE user).
- **Restore drill:** scripted restore-from-backup into a scratch env.

## 17. Quality Gates

Every Phase 4 milestone merges only when:

- Ruff no-new-errors (baseline 2), mypy no-new-errors (baseline 10), oxlint
  no-new-warnings (baseline 1).
- `pytest` full suite green (≥213) + focused milestone tests.
- Migration chain test green; `git diff --check` clean.
- Frontend `npm run build` + `npm run lint` clean (baseline only).
- Coverage gate (≥70%, target 80%).
- Terraform plan clean (P4.2+), dependency/container scans clean (P4.5).
- Backend/frontend builds boot-smoke green; Playwright smoke green (P4.6).

## 18. Risks

- **Provider drift:** GCP is implied, not confirmed; changing provider after
  P4.2 starts is expensive → resolve in owner decisions first.
- **Baseline debt:** fixing ruff/mypy during P4.1 would blur the milestone;
  keep baseline policy explicit and triage debt as P2.
- **httpOnly cookie migration** touches the token transport and can regress
  M9/M11 auth — isolate behind the owner decision and a dedicated review.
- **Redis rate limiting** changes behavior under multi-worker and proxies —
  keying on forwarded client IP requires trusted-proxy configuration; wrong
  keying breaks limits.
- **Managed Postgres cost/ops** — PITR and backups add cost; document the
  operator burden.
- **Migration ownership** — running migrations in deploy adds a single point;
  covered by pre-flight checks and rollback rehearsals.
- **Observability redaction** — any logging addition risks credential
  leakage; enforce the redaction test.
- **Technical debt NOT absorbed silently:** duplicate audit-pattern code,
  unused deps (`redis`/`tenacity`), stale root docs (QUICK_START etc.),
  unindexed audit listing — triaged in the milestone/owner decisions, not
  absorbed by Phase 4.

## 19. Owner Decisions

Required before (or during) the listed milestone:

1. **Cloud/provider + deployment target** (P4.2) — GCP/Cloud Run implied;
   confirm or choose.
2. **IaC technology** (P4.2) — Terraform (ROADMAP-preferred) vs Cloud Run YAML.
3. **Managed PostgreSQL provider** (P4.2) — Cloud SQL (implied) or other.
4. **Managed Redis provider** (P4.4) — Cloud Memorystore (implied) or other.
5. **Secrets manager** (P4.3) — Secret Manager (implied) or other.
6. **Logging/error-monitoring provider** (P4.4) — Cloud Logging + Sentry vs
   alternatives.
7. **httpOnly refresh-cookie migration** (P4.5) — adopt (transport/CSRF work)
   or retain localStorage with rotation mitigation.
8. **Frontend automated-test framework** (P4.1/P4.6) — Playwright for E2E
   (ROADMAP MUST); unit framework if added (e.g., Vitest + RTL) is a choice.
9. **Production domain** (P4.2/P4.6) — e.g., `app.<company>.com`.
10. **Google OAuth production redirect URI + hosted-domain lock** (P4.5).
11. **Main-branch merge/deploy policy** — auto vs gated production apply.

## 20. Deferred Items (beyond Phase 4)

- Multi-region/high-availability, cross-tenant SSO beyond Google, compliance
  reporting (Phase 8).
- Photo/offline/field work (Phase 6), procurement (Phase 5).
- AI/ML features (Phase 7).
- Frontend unit-test suite beyond the mandated E2E smoke (P2 hardening).
- Load test at 15-project scale (NICE TO HAVE).
- Optional pagination/indexes on list endpoints (NICE TO HAVE).
- Background job runner is SHOULD — schedule inside P4.4 if capacity allows,
  else defer with the health-recompute-now-in-request caveat.

## 21. Recommended Implementation Sequence

1. **Owner decisions 1–7, 9, 10** (freeze scope) → then:
2. **P4.1 — CI/CD & Quality Gates** (first; unblocks everything).
3. **P4.3 — Secrets & Environment Management** (prerequisite for any deploy).
4. **P4.2 — Production Infrastructure & IaC** (staging first, then prod).
5. **P4.4 — Observability & Redis-backed rate limiting.**
6. **P4.5 — Security hardening** (last-admin guard, async Google, httpOnly per
   decision, scanning, OAuth prod config).
7. **P4.6 — Staging/UAT + GO/NO-GO gate + backup/restore drill + Playwright.**

Rationale: gates and secrets first so every subsequent step is tested and
secret-safe; production infrastructure before observability so logs/alerts
have a home; security hardening immediately before the go-live gate.

---

*Owner decisions still open before implementation:* provider/IaC/secrets/
logging choices, httpOnly cookie migration, frontend test framework,
production domain, Google OAuth production redirect URI, deploy policy
(see §19). Do not implement Phase 4 until §19 items 1–10 are answered.
