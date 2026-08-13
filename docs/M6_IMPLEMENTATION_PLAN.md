# M6 — Client View-Only Scope: Implementation Plan

**Status:** PLANNED (most of the boundary already exists; this milestone
completes, hardens and verifies it — see §2).
**Branches/commits this plan assumes:** Phase 3 M1–M11 and P4.1 shipped; HEAD
`99bf282` on `claude-development`.
**Date:** Aug 12, 2026.

Source of truth: `docs/ROADMAP.md`, `docs/PRODUCT_REQUIREMENTS.md`,
`docs/CURRENT_STATE.md`, `docs/ARCHITECTURE.md`, and the code. No existing M6
plan document was found; this is the first.

---

## 1. Current M6-related implementation state

M6 was partially delivered during Phase 3 (documented in `CURRENT_STATE.md`
§4b "Client portal boundary (P3 M6)" and pinned by `tests/test_client_portal.py`,
7 tests). What already exists:

- **Backend schemas:** `ProjectClientRead` (`schemas/project.py`) is the ONLY
  project shape a client receives — name/code/site/client/schedule/status/
  progress + `completed_at`; it excludes budgets, manual health columns,
  lifecycle attribution, archive/restore bookkeeping, and internal
  created/updated timestamps. `InvoiceClientRead` (`schemas/invoice.py`) is the
  ONLY invoice shape a client sees — no notes, billing rules, or external sync
  fields; `amount` (the client's own payment request) and derived `overdue` are
  included by design (PRD §4.3.2).
- **Access control:** `project_access.assert_can_view_project` (assigned-only
  for supervisors/clients; admin/proc all; ARCHIVED → 404 for non-admin),
  `assert_not_client` (internal surfaces 403 for clients), and
  `assert_project_writable` (ARCHIVED read-only).
- **Endpoints:** clients are 403 on `GET /projects/health`, `GET
  /projects/{id}/health`, inventory items + movements + reconciliation, job
  costs + budget roll-up, billing milestones, and all write/lifecycle/
  assignment/override/user/audit endpoints. Invoices: DRAFT filtered from the
  client list and 404 on detail; SENT/PAID/CANCELLED return the restricted
  shape on assigned projects.
- **Frontend:** `ProjectDetail` skips health/inventory/archived rows for
  clients and shows `ClientInvoicesPanel`; `CommandCenter` skips the health
  roll-up and archived toggle for clients and renders a site-count KPI;
  `ProjectCard` drops health dots + budget for clients.

## 2. Requirements (ROADMAP / PRODUCT_REQUIREMENTS)

- **ROADMAP M6:** "Client view-only access: invoices + progress, no budget
  figures (role-scoped response contract)"; "must land before real clients use
  Google Sign-In"; "never leak `budget_*` to client"; sequencing guardrail —
  M6 before real clients authenticate (M11 already shipped, so M6 closure is a
  prerequisite for enabling real clients).
- **PRODUCT_REQUIREMENTS §3.4 (Client/Homeowner — view-only):** clients see
  their projects' progress, schedule, site updates, and milestone payment
  requests; never construction financials or internal admin data; read-only.
- **This milestone's goal:** guarantee, server-side, that a client can view
  only their assigned projects' permitted surfaces and can never read
  restricted financial/internal fields or mutate anything — including through
  direct API calls, nested/secondary endpoints, list vs detail, and ID
  substitution. Preserve supervisor/procurement/admin behavior exactly.

Because most of this already exists, M6 is a **close-out milestone**: verify
every surface, close any gaps the audit finds, add the missing test coverage,
and document the contract as the canonical client boundary.

## 3. Existing RBAC / access-control behavior

- `require_role(...)` dependency for role-restricted endpoints (admin,
  admin+supervisor, admin+procurement).
- `get_current_user` loads the user + enforces `is_active` (M9/M11 sessions
  unaffected).
- `assert_can_view_project` — assignment-based visibility; ARCHIVED is 404 to
  non-admin/proc (existence never leaks).
- `assert_not_client` — per-endpoint 403 for clients on internal surfaces.
- No second authorization system; clients are ordinary assigned users whose
  role gates the response contracts and surface access.

## 4. Existing client response schemas and what is missing

Existing (correct):

- `ProjectClientRead` — complete for the client portal.
- `InvoiceClientRead` — complete; DRAFT excluded at the route layer.
- No client shape exists for tasks/site logs (they reuse the shared
  `TaskRead`/`DailySiteLogRead`). These carry no money or internal finance
  fields, so reuse is acceptable; verify (and pin with tests) that they leak
  nothing.

Missing / to confirm:

- Explicit end-to-end tests for client **detail-isolation** (unassigned
  project detail → 403), **archived** project detail → 404 for clients, and
  client reads of tasks/site logs on assigned projects (allowed, restricted
  only to project-scope + no finance).
- A documented, tested **client authorization matrix** (this plan §6) so the
  boundary is reviewable in one place.
- Frontend verification that client-visible components never read fields
  absent from the client shapes (guarded by `isClient` today; add explicit
  assertions only if a gap is found — prefer server contract as the source of
  truth).

## 5. Endpoint-by-endpoint authorization matrix (target)

Legend: ✅ already enforced (verify + pin with a test); 🔲 gap to close.

| Endpoint | Client behavior (target) | Status |
|---|---|---|
| `GET /projects` | assigned projects only, `ProjectClientRead` | ✅ |
| `GET /projects/{id}` | 200 if assigned (client shape); 403 unassigned; 404 archived | ✅ (add detail-isolation test) |
| `GET /projects/health`, `GET /projects/{id}/health` | 403 | ✅ |
| `GET /projects/{id}/tasks`, `PATCH/DELETE .../{task_id}` | read 200 assigned; write 403 | ✅ (add client read test) |
| `GET /projects/{id}/site-logs`, `POST` | read 200 assigned; write 403 | ✅ |
| `GET/POST /projects/{id}/inventory`, `PATCH`, movements, reconciliation | 403 | ✅ |
| `GET/POST/PATCH/DELETE /projects/{id}/job-costs` | 403 | ✅ |
| `GET /projects/{id}/budget` | 403 | ✅ |
| `GET /projects/{id}/billing-milestones` | 403 (schedule of values is internal) | ✅ |
| `GET /projects/{id}/invoices`, `GET .../invoices/{id}` | issued-only, restricted shape; DRAFT hidden/404; 403 unassigned; 404 archived | ✅ |
| `POST .../invoices`, issue/mark-paid/cancel | 403 | ✅ |
| `POST /projects`, `PATCH /projects/{id}` | 403 | ✅ |
| Lifecycle activate/complete/archive/restore | 403 | ✅ |
| `GET/POST/DELETE /projects/{id}/assignments` | 403 | ✅ |
| `GET/POST/DELETE /projects/{id}/health-overrides` | 403 | ✅ |
| `GET /users`, `POST /users`, `PATCH /users/{id}` | 403 | ✅ |
| `GET /audit/logs` | 403 | ✅ |
| `GET /auth/me` | 200 (own user) | ✅ |

## 6. Data/field leakage analysis

Audited across list + detail + nested + rollup surfaces:

- **Money:** `budget_total`/`budget_spent` only in `ProjectRead` (admin/proc);
  supervisors and clients never receive them. Job costs, budget roll-up and
  billing-milestone rules are 403 to clients and supervisors.
- **Health:** colors/reasons/basis/overrides are 403 to clients; the health
  payload never carries money (supervisors may see it, M6 preserves that).
- **Invoices:** the only client money value is their own `amount` (a payment
  request, PRD-required); notes, billing rules, `external_*`, and attribution
  are excluded; DRAFT existence is not leaked (filtered/404).
- **Lifecycle/audit attribution:** `created_by/completed_by/archived_by/
  restored_by/restored_at/archived_at` excluded from client shapes.
- **IDs:** client-project isolation is assignment-based; substituting another
  project's UUID yields 403 (active) or 404 (archived).
- **Task/site-log reads:** project-scoped; no finance fields in those schemas.
- No server-side KPI/dashboard aggregation endpoint exists that could leak —
  the Command Center KPI is frontend-only over the client project list.

## 7. Backend changes

Likely none beyond optional hardening found by the audit; the plan's intent:

1. Re-run the audit of every endpoint in §5 against the code (already done at
   plan time — matrix shows all ✅); if a 🔲 appears, the fix is scoped to that
   route only (add `assert_not_client` or the client shape/serializer), never
   a new auth system.
2. Add the missing client tests listed in §10.
3. No schema/model/migration changes expected.

## 8. Frontend changes

1. Verify client-visible components only consume client-shape fields; fix any
   stray reference (guarded by `isClient` today).
2. Keep `ProjectDetail`/`CommandCenter`/`ProjectCard`/`KpiStrip` client gating
   as-is (already correct); do not add new client UI in M6.
3. No new dependencies.

## 9. Database / migration impact

None expected. No schema change required for the client boundary; if a 🔲 is
found that needs a column change it would be re-planned and reported first.

## 10. Test strategy and exact scenarios

Add to `tests/test_client_portal.py` (and only if a fix lands, the relevant
suite):

1. **Detail isolation:** client assigned to project A requests `GET
   /projects/{idB}` → 403 (B unassigned, active). (pin)
2. **Archived client 404:** client assigned to a project that is then archived
   → `GET /projects/{id}` and `GET /projects/{id}/invoices` → 404. (pin)
3. **Client task read allowed, write denied:** assigned client lists tasks
   (200), PATCH task → 403. (pin)
4. **Client site-log read allowed, write denied:** list 200, POST 403. (pin)
5. **Invoice shape regression:** client invoice has `amount` + `overdue`,
   lacks `notes`/billing rule/`issued_by`/`paid_by`/`cancelled_by`/`updated_at`.
6. **Unassigned client invoice detail:** `GET .../invoices/{id}` on an
   unassigned project → 403 (currently only the list is tested).
7. **Assignment revocation:** after unassign, client list/detail/invoices all
   deny (already partially covered; extend to invoices + tasks).
8. **Google-authenticated client == normal client:** reuse the M11 Google
   fixture to sign in a `client` user via Google callback and assert the same
   matrix (no authorization change from auth method).
9. **Regression:** full suite — supervisor/procurement/admin behavior
   unchanged; M9/M10/M11 suites green.

## 11. Security / threat model

- Server-side contracts are the boundary; frontend hiding is cosmetic.
- Threat: client enumerates/forges project IDs → covered by assignment check
  (403) and archived (404).
- Threat: client calls nested endpoints directly → covered by §5 matrix.
- Threat: client submits mutations manually → all writes role-gated.
- Threat: client reads financial fields via list/detail/rollup → client shapes
  omit them; money endpoints 403.
- Threat: client auth via Google elevates access → no: Google only
  authenticates; role/assignments are ICE-owned (M11 design, preserved).
- No new attack surface introduced (no new endpoints unless a 🔲 fix requires
  one).

## 12. Regression risks

- Touching project serialization risks supervisor/admin shapes → keep
  `_serialize_project` role branching intact; changes scoped to client path
  only.
- Touching invoice client list could leak DRAFT → keep the DRAFT filter/404
  behavior pinned by tests.
- Removing or changing `assert_not_client` on any surface would weaken the
  boundary → all changes additive/tested.
- M9/M11 (sessions, Google) and M10 (lifecycle/archived) interplay — full-suite
  regression required.

## 13. Rollback strategy

- If a fix is needed, it is small and endpoint-scoped; revert the single route
  change.
- Tests are additive; revert alongside.
- No migration → no DB rollback.
- The existing client boundary already deployed; worst case the milestone
  closes with verification only and no behavior change.

## 14. Acceptance criteria

- Every row of the §5 matrix is server-enforced and test-pinned.
- Client never receives `budget_*`, job costs, procurement inventory, health,
  billing rules, or internal attribution through any endpoint.
- Client cannot mutate any resource (direct API attempts → 403).
- Client A cannot access client B's project (403 active / 404 archived).
- Archived projects remain 404 to clients; supervisors/proc/admin behavior
  unchanged.
- Google-authenticated clients behave exactly like password clients.
- Full backend suite passes; frontend build/lint clean; P4.1 CI gates green;
  ruff/mypy/oxlint baselines unchanged.

## 15. Smoke-test plan

1. Local: create project + assign a client + a second project; log in as the
   client; verify Command Center shows only assigned projects, detail shows
   schedule/tasks/logs/invoices, no health/inventory/budget surfaces.
2. Direct API: with the client token, hit every §5 endpoint and assert the
   expected status/shape (scripted).
3. Google sign-in smoke for a client (M11 fixture or real config) → identical
   behavior.
4. P4.1 CI run after merge.

## 16. Documentation changes

- `docs/M6_IMPLEMENTATION_PLAN.md` — this plan (canonical).
- `docs/M6_IMPLEMENTATION_REVIEW.md` — post-implementation record.
- `docs/CURRENT_STATE.md` — M6 section updated to "complete/verified" with the
  matrix reference + new test counts.
- `docs/ROADMAP.md` — M6 marked DONE (keep the "before real clients" guardrail
  note).
- `docs/SESSION_NOTES.md` — M6 session summary.

## 17. Files expected to change

Expected (tests + docs); backend/frontend code only if the audit finds a gap:

- `backend/tests/test_client_portal.py` (add scenarios)
- Possibly `backend/app/api/v1/<route>` if a 🔲 is found (not expected)
- `frontend/src/pages/ProjectDetail.tsx`, `frontend/src/pages/CommandCenter.tsx`
  (only if a field-reference gap is found)
- `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md`,
  `docs/M6_IMPLEMENTATION_REVIEW.md`

## 18. Explicit non-goals

- No new client features (photos, chat, etc. — Phase 6).
- No new authentication/authorization system.
- No changes to M9/M11 session/Google architecture.
- No Phase 4 infrastructure work.
- No change to supervisor/procurement/admin behavior.
- No auto-provisioning of client accounts (that is the M11 `google_only`/admin
  invite flow, already in place).
- No client writes of any kind.

---

## Post-plan review (against the repository)

- **Missing requirements:** none identified — the PRD/ROADMAP client view-only
  contract is already implemented server-side; the milestone's substantive work
  is verification, test coverage, and documentation. The one actionable gap is
  **test coverage** (detail isolation, archived-404, task/site-log client
  reads, unassigned invoice detail, Google-authenticated client parity).
- **Unnecessary scope:** none proposed; the plan explicitly avoids new client
  UI and avoids touching supervisor/admin shapes.
- **Security gaps found:** none in the audit (all §5 rows already enforced);
  the plan adds pins so any future regression is caught.
- **Contradictions with M9/M10/M11:** none — clients use the normal M9 session
  path; archived-404 via `assert_can_view_project` is M10-consistent; Google
  auth does not alter authorization (M11). The M11 review's "M6 must land
  before real clients" is satisfied by this closure.
- **Migration requirements:** none.
- **Owner decisions required:** none blocking. One optional call: whether to
  enable real Google clients immediately after M6 closure (recommended to wait
  for P4 staging/gate per the Phase 4 plan) and whether `InvoiceClientRead`
  should show `overdue` (recommended keep — it is derived, not sensitive).
