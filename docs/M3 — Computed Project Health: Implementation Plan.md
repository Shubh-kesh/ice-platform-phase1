# M3 — Computed Project Health: Implementation Plan

**Milestone:** Phase 3 M3 — deterministic, explainable, rule-based Project Health for the Command Center, with audited manual override.
**Status:** PLANNING ONLY. No code changed by this document.
**Date:** August 11, 2026
**Basis:** Direct source inspection of the current codebase (`backend/app/**`, `frontend/src/**`, `docs/`), 69 passing backend tests, live Postgres.

> **Headline finding (read this first):** the codebase already contains the data needed to compute **Timeline** and **Budget** health deterministically, but it does **not** contain enough data to compute **Safety/Quality** health. The safety pillar must either be shipped as an explicit "not rated / data not captured" state, or a minimum safety-data model (proposed here as a small prerequisite milestone) must land first. This plan **does not fabricate** a safety score from the free-text `issues` column or the manual `safety_health` enum.

---

## 1. Current-state assessment

| Area | Assessment |
|---|---|
| Health fields | `timeline_health` / `budget_health` / `safety_health` **manually settable enums** on `projects` (GREEN/AMBER/RED, default GREEN), stored as columns. Verdict: **PARTIALLY IMPLEMENTED — NOT SUFFICIENT FOR M3** (hand-typed, no computation, no override tracking, no audit of the value; seed.py assigns them with `random_health()`). |
| Overall health | Computed **client-side** in `frontend/src/components/HealthDot.tsx` as **worst-of-three**. Not authoritative, not served by the API. |
| Timeline / scheduling | `tasks` table with `start_date`/`end_date`/`status`/`percent_complete`, one optional self-referential `depends_on_id`, `sort_order`. **No critical-path engine, no baseline, no planned-vs-actual, dependencies effectively decorative** (frontend never sends `depends_on_id`; no cascade re-scheduling). Known bugs: `PATCH` skips `end_date >= start_date` validation; dependency cycles allowed. Verdict: **PARTIALLY SUFFICIENT** for a coarse deterministic timeline signal using project-level `percent_complete` vs. elapsed time. |
| Budget / finance | M4 job-cost ledger: `job_costs` (`cost_code` enum, `amount`, `incurred_on`); `Project.budget_spent` derived `== SUM(job_costs.amount)` maintained in-transaction; `budget_rollup` service (total/spent/remaining/by-cost-code). Admin/proc only. Verdict: **SUFFICIENT** (this is the financial source of truth M3 must reuse). **Caveat:** `seed.py` sets `budget_spent` directly with **no** `job_costs` rows, so seeded demo projects violate the M4 invariant — budget health must read the **ledger**, and the seed must be fixed. |
| Safety / quality | **No model exists.** No inspections, checklists, defects, incidents, attendance, or toolbox-talk records. `daily_site_logs.issues` is free text (unreliable); `weather` is free text (`String(100)`), not an enum; `photo_urls` always `[]` (no upload pipeline); `safety_health` is manual/random. Verdict: **MISSING — NOT SUFFICIENT FOR M3.** |
| Inventory | Items + immutable `stock_movements` ledger + row-locked writes + reconciliation. Useful as contextual drilling data, but **not required** for the three health dimensions in M3. |
| Daily site logs | Append-only feed (`log_date`, `work_summary`, `issues`, `workers_present`, `weather`, `photo_urls`). Free-text `issues` is a possible *future* signal, **not** a reliable M3 input. |
| Audit logs | Generic `create/update/delete` trail, committed atomically with mutations. Sufficient to host health-override audit. |
| RBAC | 4 roles (`admin`, `site_supervisor`, `procurement_manager`, `client`); `project_assignments`; `project_access.py` shared helpers. **Known leak:** `ProjectRead` and the Command Center card expose `budget_total`/`budget_spent` to every role including client. |
| Lifecycle (M10) | `draft|planning|active|on_hold|completed|archived` state machine, admin-only audited transitions, ARCHIVED read-only + hidden from non-admins. M3 must be lifecycle-aware (only ACTIVE computes health). |

---

## 2. Existing data available (source-of-truth map)

| Signal | Source | Fields | Integrity |
|---|---|---|---|
| Schedule progress | `projects` | `start_date`, `target_end_date`, `percent_complete` (0–100, manual) | adequate for coarse SPI |
| Task-level delay | `tasks` | `start_date`, `end_date`, `status`, `percent_complete`, `depends_on_id` | **gap:** no PATCH date-order validation, no cycle detection → use only for overdue count, never for CPM |
| Budget | `job_costs` (ledger) | `amount` (positive), `cost_code`, `incurred_on` | `SUM(job_costs) == budget_spent` invariant (M4) — for non-seeded rows |
| Budget denominator | `projects` | `budget_total` (`Numeric(14,2)`, `>= 0`) | set on create |
| Lifecycle | `projects` | `status`, `completed_at/by`, `archived_at/by`, `restored_at/by`, `created_by` | solid (M10) |
| Safety | — | — | **none** (see §3) |
| Actor/audit | `audit_logs`, `record_audit()` | `action`, `table_name`, `record_id`, `changes` JSONB | solid; `ip_address` always NULL (pre-existing debt, out of scope) |

### Inventory & site-log data that M3 does NOT rely on
`quantity_on_hand`, `reorder_threshold`, `stock_movements`, `daily_site_logs.*` are not M3 inputs in v1. They remain readable drill-down context on the project detail page.

---

## 3. Missing prerequisites

**P0 — budget invariant for demo data (must fix first).**
`seed.py` writes `budget_spent` without `job_costs` rows, so `budget_spent != SUM(job_costs)` for seeded projects. Budget health reads the ledger, so seed must create matching `JobCost` rows (or be revised so `budget_spent` is 0 with a note). The M4 acceptance invariant must hold for every project M3 rates.

**P1 — safety/quality data model (gates the safety pillar).**
No structured safety signal exists. Minimum prerequisite model (proposed: **M12 — Safety/Quality field data**, a trimmed slice of ROADMAP Phase 6):
- `safety_incidents` — `project_id`, `occurred_on`, `category` (enum: `near_miss | first_aid | reportable_injury | asset_damage | other`), `severity` (enum: `low | medium | high`), `description`, `reported_by`, `created_at`. Append-only; audited.
- `inspections` + `inspection_items` — project-scoped checklist visits with pass/fail per item and a signed-off result (`passed | failed | deferred`), `inspected_on`, `inspector_id`.
- (Optionally) a **safe, structured** `weather` enum or safe-log incident flag — free text stays untrusted.
Until this model lands, M3 ships **Safety = NOT_RATED** (explicit grey "data not captured"), and the safety dimension is excluded — with full transparency — from `overall`.

**P2 — role-scoped project response (M6 minimum slice, interlock).**
`ProjectRead` and the Command Center card currently hand every role `budget_total`/`budget_spent`. M3's RBAC requirement (clients/supervisors must not receive internal budget figures) cannot be met while the project list leaks them. A minimal M6 scope slice must ship with (or before) M3: drop monetary fields from supervisor/client-visible project responses and replace the card's bottom "spent / total" row with a budget-health badge for those roles.

**P3 — M7 task validation (strengthens timeline v2, not blocking v1).**
`PATCH /tasks` date-order validation + dependency-cycle detection. v1 timeline uses project-level `percent_complete`; task-derived progress becomes trustworthy after M7 and can be layered on as v2.

---

## 4. Proposed health model

**On a per-dimension and per-project basis:**

- **Rating scale (extended):** `GREEN | AMBER | RED` plus a fourth, explicit **`NOT_RATED`** (grey) meaning "insufficient/immature data — deliberately not claiming a color."
- **Deterministic + explainable:** each dimension is a pure function of (project row, task/ledger rows, `today`). Every call returns:
  - `value: GREEN | AMBER | RED | None`
  - `rated: bool` (False → NOT_RATED)
  - `reasons: list[str]` (human-readable, e.g. *"Budget consumption is ahead of schedule by 7%."*)
- **Reproducible:** same committed data + same `today` ⇒ identical result. No randomness, no ML, no LLM.
- **Lifecycle gating:** health computes **only for `ACTIVE`** projects. DRAFT/PLANNING/ON_HOLD → `NOT_RATED` ("not yet in execution"); COMPLETED → **frozen** (last computed result shown with a "frozen at completion" label); ARCHIVED → not computed (hidden from non-admins; read-only; no new health).
- **Override principle:** **`computed_health != overridden_health`** — the computed result is always retained and always visible underneath a manual override (§10).

### Threshold business reasoning
Both dimensions compare a *consumption/progress ratio* to a *work-delivered baseline* (`percent_complete/100`). For 10–15 residential projects run by a small owner-operator org, a ±5% deviation is normal procurement/field variance (noise permit); >5% but ≤15% is a watch band; >15% (or any task-flag blowout) is actionable. These are stated as named constants so they are single-source and testable.

---

## 5. Timeline formula (v1 — schedule-performance-index based)

```
rate_timeline(project, tasks, today):
  if project.status != ACTIVE:                 -> NOT_RATED (reason: lifecycle)
  duration = (target_end_date - start_date).days
  if duration <= 0:                            -> NOT_RATED (reason: invalid date span)
  if today < start_date: elapsed = 0 else elapsed = min((today - start_date).days / duration, 1.0)

  progress = percent_complete / 100

  # insufficient data: nothing measurable has happened yet
  if progress == 0 and no tasks and elapsed < 0.05: -> NOT_RATED ("not started / no progress data yet")

  if elapsed < 0.05 and progress < 1:          -> GREEN (reasons: "just started, <5% schedule elapsed")
  if progress == 0:                            -> not below GREEN (no slip can be inferred)

  spi = progress / max(elapsed, 0.01)
  value = GREEN    if spi >= 0.95
  value = AMBER    if 0.85 <= spi < 0.95
  value = RED      if spi < 0.85

  # task-overdue downgrade (only ever lowers, never raises)
  overdue_fraction = (# tasks with end_date < today and status != completed) / max(len(tasks), 1)
  if overdue_fraction > 0.40: value = max(value, RED)
  elif overdue_fraction > 0.20: value = max(value, AMBER)

  reasons = [
    f"Progress {percent_complete}% vs {round(elapsed*100)}% of schedule elapsed (SPI {spi:.2f})",
    f"{n} of {m} scheduled tasks are overdue",
  ]
```

- **Source data:** `projects.start_date/target_end_date/percent_complete`, `tasks.end_date/status`.
- **Why not critical path:** dependencies are decorative, `depends_on_id` is never sent by the UI, and PATCH allows malformed dates (P3). Using project-level `percent_complete` against elapsed time is honest and robust to those gaps. Task CP-layering is explicitly deferred to a v2 after M7.
- **Expected-completion estimate (explanatory, not authoritative):** `projected_end = today + (1 - progress) * (elapsed_duration / max(progress, eps))`. Shown in tooltips as a *forecast*, labeled as derived-not-contractual.
- **Handling:** COMPLETED → frozen; DRAFT/PLANNING/ON_HOLD/ARCHIVED → NOT_RATED; valid span required; expires-never per rating (recomputed on read).

---

## 6. Budget formula (v1)

```
rate_budget(project, spent_ledger, today):
  if project.status != ACTIVE:                 -> NOT_RATED (reason: lifecycle)
  if project.budget_total <= 0:                -> NOT_RATED (reason: no budget configured)

  progress = percent_complete / 100            # work delivered
  consumed = spent_ledger / budget_total       # money used — spent_ledger = SUM(job_costs.amount)

  if spent_ledger == 0:
    if progress <= 0.15:                       -> GREEN (reason: "nothing spent yet, project early")
    else:                                      -> NOT_RATED (reason: "progress X% but zero job costs recorded — budget may be untracked")

  # hard floor: cannot be GREEN while over budget
  if consumed > 1.0 and progress < 0.99: value = max(value, AMBER)

  AHEAD_GRACE = 0.05   # allow up to 5pp under-burn before calling budget out of line
  value = GREEN if consumed <= progress + 0.05
  value = AMBER if consumed <= progress + 0.15
  value = RED   otherwise                        # consumption exceeds progress by >15pp

  # near-completion cleanup: at ≥95% complete, small overruns are normal
  if progress >= 0.95 and consumed <= progress + 0.05: value = GREEN

  reasons = [f"Budget consumption {round(consumed*100)}% vs {round(progress*100)}% physical progress "
             f"({round((consumed-progress)*100)}pp {'ahead of' if consumed>progress else 'behind'} schedule)"]
```

- **Source of truth = M4 ledger.** `spent_ledger` comes from `sum_job_costs()`/`budget_rollup()` in `app/services/finance.py`. **Never** read the `Project.budget_spent` column for health (seeded rows violate the invariant; the ledger is authoritative). No second budget calculation is introduced — M3 *reuses* the existing roll-up.
- **Partially completed projects:** exactly the case above — budget health is *consumption vs. physical progress*, so a 60%-complete project that has spent 60% of budget is GREEN, a 40%-complete project that has spent 70% is RED. Early projects (≤15% progress, zero spend) are GREEN without pretending the ledger is complete.
- **Handling:** COMPLETED → frozen; DRAFT/etc → NOT_RATED; `budget_total == 0` → NOT_RATED (no denominator); ledger-empty-with-progress → NOT_RATED (tracking gap surfaced, no misleading GREEN).

---

## 7. Safety/quality formula

**Verdict: NOT COMPUTABLE from current data. Do not fabricate.**

- v1 behaviour: `safety_rated = False` always; value `NOT_RATED`; reason *"No safety/quality data captured yet (no incident/inspection records)."* The Command Center renders a grey dot; the detail page shows a "safety tracking not configured" notice; the overall formula explicitly excludes it and says so.
- The existing manual `safety_health` column is **not** used as a computed input (it is arbitrary — seeded via `random_health()`). It is deprecated along with the other manual health fields (§13).
- **v2 formula (only after M12 data exists):**
  ```
  rate_safety(incidents, inspections):
    open high-severity incident  (severity=high, not resolved)          -> RED
    open medium/low incident  OR  any failed inspection item open        -> AMBER
    no open incidents AND an inspection passed within last N days (e.g. 30)
      AND at least one inspected item in project history                 -> GREEN
    no inspections AND no incidents at all                              -> NOT_RATED
  reasons = [per failing item / last inspection age]
  ```
- **Minimum prerequisite milestone (M12):** `safety_incidents` + `inspections`/`inspection_items` per §3-P1, with capture RBAC (supervisor/admin create; client read-only or hidden per product rule) and `record_audit` on every record. M12 is intentionally small and can land immediately after M3.

---

## 8. Overall health formula

```
rate_overall(dim_results):
  rated = [d for d in (timeline, budget, safety) if d.rated]
  if not rated: return NOT_RATED, reasons=["insufficient data for every dimension"]
  rank = {GREEN:0, AMBER:1, RED:2}
  overall = max(rank[d.value] for d in rated)   # worst-of-rated
  return overall, basis=rated names + each rated dimension's reasons
```

- **Worst-of-rated** is chosen deliberately: it is the product's existing convention (`HealthDot.overallHealth`), it is conservative for a safety/management context, and a rational "apples-to-apples" weighted average adds pseudo-precision without a defensible weighting story at this data maturity.
- **Missing dimensions never silently inflate overall:** overall is computed over **rated** dimensions only, the response carries the exact `rated_dimensions` list, and the UI must show *"Overall based on: Timeline, Budget (Safety not tracked)"* whenever any of the three is not rated. A project whose only rateable dimension is Budget shows `overall = budget`, explicitly labeled.
- **Deterministic, reproducible, testable:** pure function, unit-tested at every threshold.

---

## 9. Missing-data strategy

| Case | Behaviour |
|---|---|
| Dimension without reliable source data | `value=None`, `rated=False`, explicit `reason`; grey NOT_RATED in UI |
| `budget_total == 0` / `duration <= 0` | NOT_RATED (no denominator / invalid span), never ampere-force GREEN |
| Ledger empty while project mid-flight | Budget NOT_RATED + "budget may be untracked" flag (configurable `BUDGET_ZERO_SPEND_PROGRESS=0.15`) |
| DRAFT / PLANNING / ON_HOLD | All dimensions NOT_RATED ("not yet in execution"); not shown in health roll-ups |
| COMPLETED | Frozen last-computed result shown with "frozen at completion" label |
| ARCHIVED | Not computed; excluded from all non-admin health views; admin sees read-only last state |
| Not started / below 5% elapsed | Timeline GREEN with "just started" reason; budget GREEN with "nothing spent yet" |
| Overall when nothing rateable | NOT_RATED overall; never substituted with a hidden arbitrary green |

The **NOT_RATED** state is the antidote to "silently produce a misleading score" — a missing dimension is surfaced, not absorbed.

---

## 10. Manual override design

**Principle enforced end-to-end: `computed_health != overridden_health`.**

- **New table `health_overrides`** (append-only ratings + soft revocation):
  - `id` UUID PK, `project_id` FK, `applied_to` enum(`overall | timeline | budget | safety`)
  - `value` enum(`green | amber | red`) — override to a color, **not** to NOT_RATED (you can't override data shortage away)
  - `reason` `Text NOT NULL`, schema-validated `min_length=10` — **mandatory**
  - `set_by` FK users (admin only), `created_at`
  - `expires_at` nullable — optional limited-time override (`expires_in_days`); active while `expires_at IS NULL OR expires_at > now()`
  - `revoked_at`, `revoked_by` nullable — soft revoke (never hard-delete; full history retained)
  - **Single-active is a DB guarantee:** partial unique index `(project_id, applied_to) WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())`
- **Who/roles:** **ADMIN only** (`require_role(UserRole.ADMIN)`). Basis: overriding a health result is a management decision; supervisors influence the inputs (tasks, logs, costs), not the verdict. Procurement cannot override (but can read full budget health).
- **Which values / what it applies to:** one of the three dimensions **or** overall. Per-dimension overrides are encouraged over overall-only so the "why" stays attributable.
- **Duration:** no default expiry (a construction project may be overridden for its whole remaining life), but `expires_in_days` is supported for temporary exceptions. Overrides always require explicit revoke or expiry; both are audited.
- **Audited:** `record_audit` action `health_override` (set) with `changes = {applied_to, value, reason, expires_at}`; `health_override_revoked` on revoke. Override rows and their audit are immutable once set.
- **Computed stays visible:** every health payload returns `computed.<dim>` and `effective.<dim>`; UI contrast — *"Computed: AMBER · Override: RED (S. Sen, set 5 days ago) — <reason>"* with a link to override history.
- **Lifecycle guard:** asserting `assert_project_writable(project)` blocks overrides on ARCHIVED (read-only), consistent with every other write path.
- **API:** `POST /projects/{id}/health-overrides` (create/auto-revokes prior active for same applied_to), `GET /projects/{id}/health-overrides` (admin; history), `DELETE /projects/{id}/health-overrides/{override_id}` (soft revoke). Overrides do not modify computed results in any way.

---

## 11. RBAC / visibility rules

| Role | Command Center list | Health visibility detail | Monetary budget fields | Override |
|---|---|---|---|---|
| `admin` | All (+ `?include=archived`) | Full computed + effective + reasons + override history | Yes (M4) | **Yes** |
| `procurement_manager` | All (+ archived) | Full computed + effective + reasons (budget amounts stay in the existing `/budget`, `/job-costs` endpoints) | Yes (M4) | No |
| `site_supervisor` | Assigned only | Health badges + reasons for all rated dimensions (incl. **budget color only** — no numeric values); timeline/safety reasons | **No** | No |
| `client` | Assigned only | Health badges + non-financial reasons (timeline/safety); budget badge shown or hidden per owner decision — **never** dollar figures | **No** | No |

- The new health DTOs **never contain monetary values** — budget health is a derived color. Enforcing the "no internal budget figures" rule therefore costs nothing in the health payload itself.
- **Interlock/P2:** the standalone `ProjectRead` + Command Center card **do** currently leak `budget_total`/`budget_spent` to supervisor/client. The minimal M6 scope slice (role-gated project serialization + card rework) is a hard prerequisite for the M3 RBAC requirement. Decision needed: fold that slice into M3 (recommended) or land M6 just before the M3 UI.
- Archived: unchanged M10 rules (404 for non-admins; health roll-ups exclude archived unless admin/proc `?include=archived`).

---

## 12. API design

New, compute-on-read endpoints under the existing `/projects` router. **Route-order gotcha:** `GET /projects/health` must be registered **before** `GET /projects/{project_id}` in the router (the UUID-typed path param would otherwise 422 on the literal `health`). Register roll-up first and cover with a regression test.

- `GET /api/v1/projects/health` — authenticated, role-scoped list roll-up for the Command Center (same visibility/archived rules as `GET /projects`, incl. `?include=archived`). Returns `list[ProjectHealthRead]`.
- `GET /api/v1/projects/{id}/health` — single project health (project-scoped via `assert_can_view_project`). Returns `ProjectHealthRead`.
- `POST /api/v1/projects/{id}/health-overrides` — admin; creates/auto-revokes the previous active override for `(project, applied_to)`.
- `GET /api/v1/projects/{id}/health-overrides` — admin history.
- `DELETE /api/v1/projects/{id}/health-overrides/{override_id}` — admin; soft revoke.
- **Deprecation:** remove `timeline_health/budget_health/safety_health` from `ProjectUpdate` (they are the manual path M3 replaces, and they bypass precise audit). Health changes happen either by data (computed) or by override (audited) — never by PATCH.

**Schemas (new):**
```python
class ProjectHealthRead(Base):
    project_id, status
    computed: dict[Dim, {value: HealthStatus|null, rated: bool, reasons: list[str]}]
    effective: dict[Dim, HealthStatus|null]        # computed unless overridden
    overall: {computed, effective, basis: list[Dim]}
    override: {applied_to, value, reason, set_by, set_at, expires_at} | None  # admin/proc only field
    data_sufficiency: {timeline: bool, budget: bool, safety: bool}
```
`override` is only populated for admin/procurement (it never carries money, so the rest is safe for supervisor/client).

---

## 13. Database changes

- **New table `health_overrides`** (columns per §10) + partial unique index `(project_id, applied_to) WHERE revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())`.
- **`projects`:** no new columns. Computed health is **derived on read** from source-of-truth rows — no denormalized health columns. Rationale: 10–15 projects ⇒ the entire roll-up resolves in a handful of indexed queries; denormalization buys nothing here and risks staleness/divergence (the exact failure mode M1/M4 eliminated for stock/budget). If Command Center latency ever matters at scale, the existing TanStack Query 30s staleTime already absorbs recompute cost client-side; a Redis/worker recompute is explicitly a Phase 4 concern.
- **Manual health columns** (`timeline_health`, `budget_health`, `safety_health`): left in place for a transient migration window (non-breaking) but **deprecated** — `ProjectUpdate` stops accepting them, health computation ignores them, seed stops setting them. Optional later migration to drop/null them once override history covers the data.
- **Alembic migration** for `health_overrides` (single revision, additive).

---

## 14. Frontend changes

- `frontend/src/types/index.ts` — add `ProjectHealth`, `Dimension`, `NOT_RATED` (`null | undefined` + `rated:false`), override types.
- `lib/api.ts` — `getProjectsHealth()`, `getProjectHealth()`, `setHealthOverride()`, `revokeHealthOverride()` helpers.
- `HealthDot.tsx` — add grey/NOT_RATED state + optional `reason`/`detail` tooltip; **overall comes from the server** (replace the client-side worst-of-3 with `effective.overall` so override/missing-data logic is single-source).
- `KpiStrip.tsx` — count from server `effective.overall`; add a "not rated / data gap" count.
- `ProjectCard.tsx` — health row uses `effective` per-dimension (grey dots where NOT_RATED); hover/title shows first reason sentence; bottom `spent / total` row becomes **role-gated**: admin/procurement keep amounts, supervisor/client get the budget **badge only** (M6-slice).
- `ProjectDetail.tsx` — new **Health panel** (`id="health"`? — note: existing panels are `ProjectTimeline`, `DailySiteLogs`, `InventoryPanel`, `JobCostsPanel`, `ProjectAssignments`): per-dimension computed vs effective, reasons lines, NOT_RATED notices, safety "not tracked yet" callout, and admin-only override form (`applied_to`, value, reason, optional `expires_in_days`) + override history list.
- Screenshot-quality example of the target UX:
  ```
  PRJ-2026-0001  ·  Overall: YELLOW (AMBER)
     Timeline  🟢  "Progress 55% vs 60% of schedule elapsed"
     Budget    🟡  "Budget consumption 62% vs 55% progress — 7pp ahead of schedule"
     Safety    ⚪  "No safety/quality data captured yet"
     Overall based on: Timeline, Budget (Safety not tracked)
  ```

---

## 15. Audit requirements

- **Only health mutation is the override:** `POST/DELETE health-overrides` each call `record_audit` in the same transaction (`health_override` / `health_override_revoked`, changes include `applied_to`, `value`, `reason`, `expires_at`).
- Computed health is *derived*, so its history is the history of its inputs (tasks, job costs, lifecycle) — already audited. No synthetic recompute events in v1 (optional v2: log "dimension flipped state" on write paths).
- Override rows are never hard-deleted; revocation is a mutable timestamp on an otherwise-immutable record (append-only convention like `daily_site_logs`/`audit_logs`).
- `projects` manual health fields removed from PATCH means the single source of health-change audit is the override trail.

---

## 16. Test plan

**Unit tests — pure formula functions (`app/services/health.py`):**
- Timeline: thresholds `SPI 0.95/0.85`; elapsed clamp (`today < start`, `today >= end`, zero duration); `percent_complete == 0/100`; just-started band; overdue downgrade at `>0.20` and `>0.40`; overdue never upgrades; NOT_RATED (DRAFT, invalid span, no data yet).
- Budget: thresholds `progress+0.05 / +0.15`; `budget_total == 0`; `budget_spent == 0` with progress >/≤ `0.15`; ledger-vs-column divergence (uses ledger); over-budget floor; near-completion cleanup; decimal/float rounding boundaries.
- Overall: worst-of-rated; empty-rated → NOT_RATED; `rated_dimensions` correct when safety unrated; determinism (same inputs twice ⇒ same outputs).
- Override: expiry math, single-active, revoke, reason min-length.

**API/integration tests (`tests/test_health.py`):**
- ACTIVE projects with controlled task/job-cost fixtures → expected per-dimension + overall; roll-up `GET /projects/health` matches detail per project.
- **Route ordering:** `GET /projects/health` returns the roll-up, not a 422/404 (regression for the `/{project_id}` shadowing).
- RBAC: client/supervisor health responses contain **zero** monetary fields; procurement sees full computed+effective; only admin can POST/DELETE overrides (supervisor 403); client on another project 404.
- Override lifecycle: set → `effective` changes while `computed` unchanged; second set on same `applied_to` revokes first; revoke → back to computed; expiry honored; override blocked on ARCHIVED (403); audit rows exist with reason.
- Lifecycle: DRAFT → all NOT_RATED; COMPLETED → frozen; ARCHIVED excluded from non-admin roll-ups; `?include=archived` for admin.
- Client isolation (P2): after role-scoped response, client `GET /projects` has no `budget_total`/`budget_spent`.
- Seed ledger fix: after seeding, `budget_spent == SUM(job_costs)` holds for every seeded project.
- Regression: existing 69 tests stay green.

---

## 17. Acceptance criteria

1. Every ACTIVE project gets Timeline + Budget health and an Overall; identical committed data + same date ⇒ identical result (deterministic, reproducible).
2. Threshold boundaries for both dimensions are unit-tested and documented with business reasoning (§4).
3. DRAFT/PLANNING/ON_HOLD → NOT_RATED; COMPLETED frozen; ARCHIVED excluded (non-admin) and read-only (no override).
4. Missing dimensions never silently mislead — `rated_dimensions`/`basis` are explicit; Safety is NOT_RATED with a visible reason until the M12 data model exists; no fabricated safety score.
5. `computed_health != overridden_health`: overrides are admin-only, reason-mandatory, single-active, optional-expiry, audited, never hard-deleted; computed result always visible beneath.
6. Clients and supervisors receive no internal budget/job-cost figures through any health or project response (P2/M6 slice).
7. Budget uses the M4 ledger only; the `budget_spent == SUM(job_costs)` invariant holds for all projects including seeded/e2e fixtures.
8. Command Center roll-up for ~15 projects resolves in a small constant number of queries (no N+1); frontend renders badges, tooltips/reasons, NOT_RATED grey, and admin override UI.
9. `GET /projects/health` is not shadowed by `GET /projects/{project_id}`.
10. Existing 69 tests + new `test_health.py` green; ruff/tsc clean.

---

## 18. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Seed data violates the budget invariant | Budget health (ledger-based) diverges from displayed `budget_spent` | Fix seed to create matching `JobCost` rows (P0) before computing on real demo data |
| `percent_complete` is manual/coarse | Timeline sensitivity is limited | Large tolerance band; label reasons with "based on % complete"; task-derived progress deferred to v2 (post-M7) |
| Task PATCH allows malformed dates/cycles (P3) | Overdue count could reflect dirty data | Timeline uses overdue only as a downgrade and only when `end_date` is sane; M7 scheduled |
| Manual health fields were seed-random | Existing UI colors will change after M3 ("why is the dot grey now?") | Communicate the deprecation; refresh seed; keep NOT_RATED tooltip explaining the change |
| Clients silently keep seeing budgets (P2) | RBAC requirement unmet despite correct health DTOs | Land the role-scoped project response + card rework with M3 |
| Route shadowing `/projects/health` | 422/404 on the roll-up | Register roll-up before `/{project_id}`; regression test (§5-route) |
| Stale overrides without expiry | Health no longer reflects reality | Visible override metadata + history; admin review surface; optional expiry supported |

---

## 19. Dependencies

- **P0** seed/ledger invariant fix (small, self-contained).
- **M6 minimal slice** (role-scoped project response + card) — prerequisite for the RBAC acceptance criterion; recommend folding into M3.
- **M7** task date-order + cycle detection — enables timeline v2 (task-derived progress); not blocking v1.
- **M12 (proposed)** safety-incidents + inspections data model — gates the safety pillar; without it Safety ships as explicit NOT_RATED.
- Reuse: `app/services/finance.py` (`sum_job_costs`/`budget_rollup`), `app/services/projects.py` (lifecycle), `project_access.assert_can_view_project/get_project_or_404/assert_project_writable`, `require_role`, `record_audit`, M10 lifecycle gates.
- Not required: inventory data, photo pipeline, workers/queue, Redis.

---

## 20. Recommended implementation order

1. **Seed ledger fix (P0)** — seeded projects satisfy `budget_spent == SUM(job_costs)`.
2. **`app/services/health.py`** — pure formula functions (timeline §5, budget §6, overall §8, missing-data guards §9) + unit tests. Deterministic foundation for all future AI phases (this is the layer that later becomes callable by ML features without touching routes).
3. **Health endpoints** — `GET /projects/health` (declared before `/{project_id}`) + `GET /projects/{id}/health`; schemas; wired to finance lifecycle services; route-order regression test.
4. **M6 minimal slice (P2)** — role-gated project serialization; Command Center card + KPI use health payload; **no budget figures for supervisor/client**.
5. **`health_overrides`** — migration, model, admin endpoints, audit, tests (§10, §15, §16).
6. **Frontend** — types/api, HealthDot NOT_RATED + reasons, cards/KPI, Project Detail health panel + override form/history; client-facing tooltips incl. "Overall based on: Timeline, Budget (Safety not tracked)".
7. **M12 proposal review** — safety-incidents + inspections design; when approved, wire §7-v2 into the same `health.py` with no API break.
8. **Docs** — update `CURRENT_STATE.md`, `ROADMAP.md`, `SESSION_NOTES.md` after review and, separately, after implementation.

**Deliberately out of scope for M3:** LLM/ML scoring, predictive delay, weather forecasting, CV-based QC, weighted/ML overall scores, denormalized health caching, background recompute jobs (Phase 4).