# M6 — Client View-Only Scope — Implementation Review

**Status:** IMPLEMENTED, verified (not yet committed).
**Date:** Aug 13, 2026.
**Plan:** `docs/M6_IMPLEMENTATION_PLAN.md` (source of truth for intent).
**Finding that shaped the milestone:** M6's core server-side boundary already
existed from Phase 3; this milestone was a security/contract **close-out** —
audit every client surface, add regression pins for the identified gaps, and
document the boundary. No authorization architecture was redesigned and no
second RBAC system was introduced.

## 1. Implementation summary

A full endpoint audit confirmed every client-accessible surface already enforces
the M6 contract server-side (`ProjectClientRead`, `InvoiceClientRead`,
`assert_not_client`, `assert_can_view_project`, DRAFT-invoice filter/404, 403
on health/inventory/finance/milestones/all writes, frontend `isClient` gating).
The only code change was **test coverage**: `tests/test_client_portal.py` grew
from 7 to 17 tests, pinning the previously untested gaps.

## 2. Why each change was necessary

- The plan identified test gaps (detail isolation, archived-404, client task/
  site-log reads, unassigned invoice detail, Google parity, consolidated
  mutation/IDOR/money-leak pins). Closing them required no backend change —
  the existing guards already produced the correct behavior, which the new
  tests now prove and protect against regression.

## 3. Exact files changed

- `backend/tests/test_client_portal.py` — +442 lines, 10 new tests.
- `docs/M6_IMPLEMENTATION_REVIEW.md` — this document (new).
- `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md` — M6
  status updates.
- No backend/frontend application code changed. No migration.

## 4. Endpoint/RBAC matrix (verified)

All rows from the plan's matrix hold (clients): list/detail = assigned-only
`ProjectClientRead` (403 unassigned, 404 archived); health roll-up + detail =
403; tasks + site-logs = read 200 assigned (no money fields), writes 403;
inventory/job-costs/budget/billing-milestones = 403; invoices = issued-only
restricted shape, DRAFT hidden/404, unassigned 403, archived 404; project
PATCH, lifecycle, overrides, assignments, users, audit = 403. Supervisors keep
health + restricted no-money project shape; admin/procurement keep budgets and
finance; Google-authenticated clients behave identically.

## 5. Data-leakage verification

Pinned by tests: client project payloads contain only
`id/project_code/name/site_address/client_name/start_date/target_end_date/
status/percent_complete/completed_at`; budget/budget_spent/health columns/
lifecycle attribution/internal timestamps are absent (asserted on the actual
serialized JSON). Task/site-log client reads carry only project-scoped progress
fields (no money keys). Client invoice payloads carry `amount` + `overdue` and
exclude `notes`, billing rules, `external_*`, and attribution. Verified on
serialized responses, not status codes.

## 6. IDOR verification

New tests: client A requesting client B's active project detail → 403; client
A requesting B's tasks/site-logs/inventory → 403; unassigned invoice detail →
403 (guard runs before resource lookup).

## 7. Mutation protection verification

New consolidated matrix test asserts 403 for: project create/PATCH, all four
lifecycle transitions, health-override create/delete, inventory create/PATCH/
movement, job-cost create, milestone create, invoice create, assignment
grant/revoke, user create/PATCH, and audit read. Plus task/site-log writes in
the read-shape test.

## 8. Google-client parity

New test completes a real Google callback (M11 path) for the client user and
asserts identical behavior to the password client: client project shape, 403
on unassigned detail / health / inventory, restricted invoice shape with
correct `amount`, 403 on task write, `role == "client"` on `/auth/me`.

## 9. Test results

- `pytest -q tests/test_client_portal.py`: **17 passed**.
- `pytest -q` (full suite, incl. migration chain): **223 passed** (was 213).
- Ruff: 2 baseline findings unchanged. Mypy: 10 baseline findings unchanged.
  Oxlint: 1 baseline warning unchanged (baseline-delta gates PASS).

## 10. Frontend results

- `npm run build`: passed. `npm run lint`: 1 baseline warning only.

## 11. Migration status

No database migration. No schema/model change. Alembic head unchanged
(`i7d8e9f0a1b2`); migration-chain test green within the full suite.

## 12. Regression results

Full suite 223 passed — supervisor/procurement/admin behavior unchanged (new
compact role-regression test), M9/M10/M11 suites green, health/archive/invoice
behavior intact.

## 13. Deviations from M6_IMPLEMENTATION_PLAN.md

- No backend/frontend code changes were required — the audit found the boundary
  already complete, so §7/§8 of the plan resolved to "no change needed." This is
  the intended close-out outcome, not a scope reduction.
- Test shape assertions for task/site-log reads use a money-only deny-list
  (`CLIENT_MONEY_KEYS`) rather than the project `CLIENT_FORBIDDEN_KEYS`, because
  task/site-log `created_at`/`updated_at` are legitimate progress metadata, not
  finance leakage.

## 14. Remaining concerns

- Frontend has no automated unit/E2E tests (pre-existing; E2E Playwright is
  P4.6).
- Enabling real Google-authenticated clients should still wait for the Phase 4
  staging/gate (P4.6) per the ROADMAP guardrail.

## 15. Final verdict

**SAFE TO REVIEW.** The M6 client view-only contract is verified end-to-end
server-side with regression coverage for isolation, IDOR, leakage, mutation
protection, archived-404, and Google parity. No application code, migration,
or auth behavior was changed; baselines and the full suite are green.
