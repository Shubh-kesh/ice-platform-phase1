# ICE Platform — Session Handoff

Current working-session handoff. **Not** a historical document — describes the
**currently verified** repository state so a completely fresh OpenCode session
can continue without this conversation's context. Facts in this file were
re-verified on Aug 13, 2026; trust code/tests over any stale wording here.

## 1. Handoff Status

- **Date:** Aug 13, 2026 (session).
- **Branch:** `claude-development`; **HEAD:** `7795890` (M6 close-out test
  commit), **ahead of origin by 1** (M6 close-out not yet pushed).
- **M13 (`3315957`) is committed AND pushed** to `origin/claude-development`.
- **Working tree:** no modified tracked files; 7 untracked docs (see §8).
- **Database and repo are in sync** at Alembic `j8e9f0a1b2c3` (M13).

## 2. Current Project State

- **Completed milestones (all committed):** Phase 1, Phase 2, M1–M13, P4.1
  (one-line list in `docs/AI_CONTEXT.md` §3). M6 close-out is the newest
  commit; M13 is the newest milestone commit, pushed.
- **Alembic current = heads = `j8e9f0a1b2c3`** (M13 `notifications`), verified
  in sync; the local dev DB was upgraded in place (no drop/reset).
- **Backend tests:** **256 passing** (verified Aug 13, 2026), incl. 12 M13
  notification, 21 M12 scheduling, 20 M11 Google, 17 M6 client-portal, and
  the migration-chain test through `j8e9f0a1b2c3`.
- **Frontend:** `npm run build` passes; `npm run lint` passes with 1
  pre-existing warning (`auth-context.tsx` Fast Refresh).
- **Quality gates:** ruff 2 / mypy 10 baselines met (delta gates PASS);
  `git diff --check` clean.
- **Deployment/demo:** dev/demo runs on Docker Compose + Vite; Render.com is
  the documented demo target; Phase 4 production rails **deferred** (P4.1
  CI/CD only is done).

## 3. Committed Work

| Commit | What |
|---|---|
| `7795890` | **test: close out client portal security boundary (M6)** — `backend/tests/test_client_portal.py` +442 lines, 7→17 tests (detail isolation, archived-404, task/site-log read shapes, invoice allow/deny, unassigned-invoice 403, financial isolation, mutation matrix, IDOR, Google-client parity, role regression). |
| `3315957` | **feat: add in-app notifications and alerts (M13)** — notifications table + migration `j8e9f0a1b2c3`, service, user-scoped API, 4 event hooks, `NotificationsBell`, 12 tests. Pushed. |
| `dc8c49c` | **feat: add task dependency scheduling cascade (M12)** — `apply_schedule`, `task_schedule_shift` audit, timeline dependency picker. |
| `99bf282` | **ci: add automated quality gates (P4.1)** — `.github/workflows/ci.yml` + baseline delta gates. |

Pre-M12 history is unchanged (see `git log`).

## 4. Current Worktree State

No modified tracked files. Untracked docs only:

- `docs/AI_CONTEXT.md` — LLM bootstrap (regenerated this session).
- `docs/SESSION_HANDOFF.md` — this file (regenerated this session).
- `docs/M6_IMPLEMENTATION_PLAN.md` — M6 scope (pre-implementation plan).
- `docs/M6_IMPLEMENTATION_REVIEW.md` — M6 close-out verification record.
- `docs/M12_IMPLEMENTATION_PLAN.md` — M12 approved scope (M12 review is
  committed; the plan was deliberately left uncommitted).
- `docs/M13_IMPLEMENTATION_PLAN.md` — M13 approved scope (M13 review is
  committed; the plan was deliberately left uncommitted).
- `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md` — Phase 4 P4.2 owner-decision
  pass (D1–D9 unapproved; no infra implemented).

These 7 docs are ready to be committed as documentation (they were left out of
the M13 and M6 commits by design, per the earlier handoff). None is required
for the next milestone to proceed.

## 5. Deferred Work

- **Phase 4 P4.2–P4.6 (production infrastructure):** IaC, managed Postgres/
  Redis, secrets, observability, Redis rate limiting, staging/GO-NO-GO gate.
  Blocked on owner approval of D1–D9 (recommended: GCP Cloud Run + Cloud SQL
  + Memorystore + Secret Manager + Workload Identity). See
  `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md`.
- **Email/SMS/web-push notification delivery** (M13 is in-app only).
- **7-day low-stock demand forecast** (Phase 5; needs a worker).
- **httpOnly refresh-cookie transport** (M9-deferred; needs HTTPS env).
- **Frontend automated/E2E tests** (Playwright smoke is Phase 4).
- **Phase 5/6/7/8** features — planned, not started.

## 6. Next Recommended Milestone

From `docs/ROADMAP.md`. Phase 4 production rails are deferred pending owner
decisions, so the next implementable feature milestone is **Phase 5's first
milestone: Vendors + Purchase Orders (PO lifecycle + line ops)** — it extends
the existing finance/inventory/notifications pillars with no new infrastructure
dependency and high business value (material spend control). A smaller
alternative: an "integrity close-out" milestone (the two uniqueness stubs,
audit-list index, M11 last-admin lockout guard) before starting new features.

**Not approved yet** — before implementing, create/approve the milestone
implementation plan (see §7).

## 7. Unresolved Owner Decisions

- **P4.2 D1–D9** (provider/IaC/DB/Redis/secrets/domain/backup/IAM/staging) —
  documented in `docs/P4.2_INFRASTRUCTURE_DECISION_REPORT.md`.
- **Email/push notification delivery** (provider + secrets).
- **Whether to enable real Google-authenticated clients** immediately after M6
  close-out or wait for the Phase 4 staging/gate (ROADMAP guardrail favors
  waiting).
- **Next feature milestone selection** (Vendors+POs vs integrity close-out vs
  Phase 6 photos/offline).

## 8. Important Architectural Decisions (do not accidentally reverse)

Verified in the repository; treat as authoritative:

- **Phase 4 production infrastructure is deferred** (P4.1 only is done).
- **Render** is the documented feature/demo deployment target; local dev is
  Docker Compose + Vite; GCP/Cloud Run is the recommended (unapproved) P4.2
  stack.
- **M13 is in-app notifications only**; email/push deferred; notification
  creation is transactional with its triggering event; recipient model:
  schedule→assigned supervisors+admins, invoice→assigned client+admins,
  low-stock→**global** procurement+admins (procurement is not
  project-assignable), assignment→user.
- **M6 client boundary is server-enforced and test-pinned** (17 tests).
- **M9 session architecture and M11 Google auth remain authoritative.**
- **Migration discipline:** one linear Alembic chain; additive revisions;
  chain-tested upgrade/downgrade/replay; dev DB applies migrations at startup
  (`alembic upgrade head` in the compose command).

## 9. Known Risks / Technical Debt (top items)

- Production/deployment rails deferred (no IaC, secrets manager,
  observability, Redis-backed rate limiting, staging/gate); refresh token in
  `localStorage`; in-memory per-process rate limiting.
- Baseline tooling debt (must not increase): ruff 2, mypy 10, oxlint 1.
- Non-blocking: sync `httpx` in async Google handlers; admin self/last-admin
  lockout guard; no frontend tests; audit-list index; two uniqueness stubs.
- Full details: `docs/CURRENT_STATE.md` §5–§8.

## 10. Source of Truth

- `docs/AI_CONTEXT.md` = bootstrap/navigation (regenerated this session).
- `docs/CURRENT_STATE.md` = current verified project state.
- `docs/ARCHITECTURE.md` = architecture/invariants (note: older, predates
  M10–M13 endpoints — verify endpoint surfaces in code).
- `docs/ROADMAP.md` = future direction.
- Milestone `*_IMPLEMENTATION_PLAN.md` = approved scope (before).
- Milestone `*_IMPLEMENTATION_REVIEW.md` = implementation verification (after).
- `docs/SESSION_HANDOFF.md` = current-session continuation state.
- Code and tests are the ground truth; any doc conflict resolves in their
  favor.
