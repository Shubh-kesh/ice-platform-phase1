# M12 — Dynamic Gantt & Dependency Scheduling: Implementation Plan

**Status:** PLANNED (not implemented). No code, migrations, or commits created.
**Date:** Aug 13, 2026.
**Branches/commits this plan assumes:** M1–M11 + M6 close-out + P4.1 shipped on
`claude-development`; Alembic head `i7d8e9f0a1b2`. Phase 4 infrastructure
(P4.2–P4.6) is intentionally **postponed** — M12 must not depend on it.
**Source of truth:** `docs/ROADMAP.md`, `docs/CURRENT_STATE.md`,
`docs/ARCHITECTURE.md`, `docs/PRODUCT_REQUIREMENTS.md` (PRD §4.1.2), and the
code. This is the plan; the post-implementation record belongs in
`docs/M12_IMPLEMENTATION_REVIEW.md`.

---

## 1. Objective

Make the Gantt/timeline **dependency-consistent**: when an upstream task's
schedule changes, downstream dependent tasks automatically shift so that
dependency constraints remain valid, with the server authoritative. Extend the
existing M7 dependency/date validation (already present) into actual
scheduling, wire dependency editing into the timeline UI, and keep every
existing guarantee (M7 cycle/date checks, project row locking, M8 idempotency,
M9/M11 auth, M6 client read-only, RBAC, audit) intact.

## 2. Current implementation state (verified against code)

**Model** (`app/models/task.py`): `tasks` has `project_id` (FK CASCADE),
`name`, `start_date`, `end_date` (DATE, non-null), `status`, `percent_complete`,
`depends_on_id` (single optional predecessor, FK `tasks.id` ON DELETE SET
NULL), `sort_order`, timestamps. Dates are **calendar days**, inclusive
(`end_date >= start_date`).

**Schema** (`app/schemas/task.py`): `TaskCreate`/`TaskRead` include
`depends_on_id`, `sort_order`, dates; `TaskUpdate` already includes
`depends_on_id` and enforces date-order when both dates are set.

**API** (`app/api/v1/tasks.py`): `GET/POST /projects/{id}/tasks`,
`PATCH/DELETE /projects/{id}/tasks/{tid}`. Read = `assert_can_view_project`
(assigned; archived → 404). Write = admin or **assigned** supervisor via
`_assert_can_write`, which takes the **project row lock**
(`get_project_for_update`) — the M7 serialization point. PATCH already handles
`depends_on_id` (self/same-project/cycle checks) and validates merged dates
before mutating. Audit = single `create`/`update`/`delete` row for the edited
task.

**Service** (`app/services/tasks.py`): `validate_task_dates`,
`validate_dependency` (same-project + not-self), `get_project_tasks` (all
tasks, one query), `detect_dependency_cycle` (iterative, bounded), and
`predecessor_map`. **No Finish-to-Start enforcement and no scheduling exist** —
`depends_on_id` is today only a validated display edge.

**Frontend** (`ProjectTimeline.tsx`, `ProjectDetail.tsx`): minimal Gantt bars
(no charting library). Create form has name/start/end but **no dependency
picker**; per-task controls only edit `status`/`percent_complete`; **no date
editing**; delete button. `canWrite` (admin/supervisor) gates all write
controls; clients are read-only (`isClient`). The timeline is invalidated after
mutations so the list refetches.

**DB** (migration `8f3a1c2d9e01`): `depends_on_id` UUID nullable, FK
`tasks.id` SET NULL, `project_id` FK CASCADE + `ix_tasks_project_id`. No index
on `depends_on_id`.

## 3. PRD requirements

PRD §4.1.2 "Dynamic Gantt Charts": task scheduling with dependencies; when an
upstream task's date changes, all subsequent dependent tasks shift
automatically; notification to vendors when a schedule change affects them.
Acceptance: "Changing task dates updates downstream schedule and triggers
vendor notifications." **M12 scope:** the automatic downstream shift. Vendor
notifications are out of scope (see §23; they are the separate notifications
gap and may need email infrastructure).

## 4. Existing M7 behavior (must be preserved exactly)

- `end_date >= start_date` on create (schema) and on PATCH (merged-state check).
- `depends_on_id` must reference an existing task **in the same project** and
  never the task itself.
- No dependency cycles (single-edge, bounded iterative walk).
- All task writes serialize on the project row lock; validation runs against
  the latest committed state; a failed request never leaves a half-applied
  change.
- Deterministic list order: `sort_order, start_date`.

## 5. Functional requirements

1. `depends_on_id` is editable from the timeline UI (create + per-task edit).
2. Finish-to-Start (F-S) constraint is enforced server-side: a task cannot
   start before its predecessor ends + 1 calendar day (recommended; see D3).
3. When a task's dates change such that a dependent violates F-S, the server
   shifts the dependent (and transitively its dependents) so the constraint
   holds — deterministic and idempotent.
4. The schedule recomputes automatically on every task create/PATCH/delete
   (no separate recalculation endpoint; see D9/D10).
5. Dependency display: predecessor name/edge shown in the timeline; a "N tasks
   shifted" notice when a cascade occurs.
6. Clients remain read-only; admin/supervisor write authorization unchanged;
   M6/M11/M9 guarantees intact.
7. Existing M7 date-order and cycle validations remain the first gate.

## 6. Scheduling semantics (recommendations from the actual codebase)

- **Meaning of `depends_on_id` today:** one optional predecessor, validated
  (same project, not self, no cycle) and drawn as a line; **not** currently
  constrained in time. M12 adds the time constraint (F-S).
- **F-S:** successor `start_date >= predecessor.end_date + 1 day` (calendar
  days; dates are day-granular and inclusive).
- **Weekends/non-working days:** not modeled anywhere (no calendar table).
  M12 keeps plain calendar-day arithmetic (D8).
- **Durations:** implied by `end_date - start_date + 1`; no separate column.
- **Upstream moves forward (later):** dependents that would now violate F-S are
  pushed forward by the minimum needed (their duration preserved), transitively.
- **Upstream moves backward (earlier):** dependents already satisfy F-S; they
  are **not** pulled back (push-only enforcement; D2/D4 — manual placement is
  never overridden backward).
- **Duration change:** same cascade — if a task's `end_date` moves later,
  dependents shift; if it moves earlier, dependents keep their dates.
- **Dependency removed / predecessor deleted:** FK `SET NULL` clears the edge;
  the dependent keeps its current dates (no shift; D5).
- **Dependency changed to a later predecessor:** re-evaluated; dependent shifted
  forward if it now violates F-S against the new predecessor.
- **Chains of 2/3/10+:** cascade traverses the transitive closure in one pass;
  bounded by task count; cycles are impossible (M7).
- **Diamonds / multiple predecessors:** schema allows at most **one**
  predecessor per task (single `depends_on_id`), so no diamonds in the
  multi-predecessor sense; one task may fan out to many successors. M12 keeps
  the single-predecessor model (D7).

## 7. Owner decisions (explicit)

| # | Decision | Options | Recommendation & rationale | Impact |
|---|---|---|---|---|
| D1 | Cascade mode | (a) Push-only constraint enforcement; (b) full pull-back cascade; (c) advisory/warning-only | **(a)** Only shift forward when F-S would be violated; never move manual dates backward. Safest, deterministic, matches "constraints remain valid". | Backend algorithm; tests; UX |
| D2 | Direction | forward-only vs both-direction | **forward-only** (with D1) | Backend; tests |
| D3 | F-S boundary | `>= end + 1 day` vs `>= end` (same-day overlap) | **`>= end + 1 day`** — day-granular, inclusive bars; standard F-S | Backend; tests; UI hint |
| D4 | Override downstream manual dates | never beyond minimum shift vs always realign offset | **minimum shift only** | Backend; tests |
| D5 | Predecessor deleted | keep dependent dates vs recompute | **keep** (FK SET NULL already) | Tests only |
| D6 | Duration change | cascade dependents vs leave | **cascade** (same rule) | Backend; tests |
| D7 | Multiple predecessors | keep single `depends_on_id` vs many-to-many | **keep single** (schema + FK unchanged; multi-predecessor deferred) | none (no migration) |
| D8 | Non-working days | not modeled vs calendar table | **not modeled** (plain calendar days; PRD silent) | none |
| D9 | Trigger | automatic on every task mutation vs explicit endpoint | **automatic** on create/PATCH/delete | Backend; tests |
| D10 | Recalculate endpoint | none vs `POST /tasks/recalculate` | **none** — every mutation re-schedules; PATCH is idempotent/self-healing | none |
| D11 | Migration/index | none vs index on `depends_on_id` | **none** (schema sufficient; single-query project load) | none |
| D12 | Audit of shifted dependents | separate action e.g. `task_schedule_shift` (one row per shifted task) vs fold into the user task's `update` | **separate `task_schedule_shift` rows**, one per shifted dependent, same transaction | Audit; tests |
| D13 | Response metadata | include `shifted_task_ids` in PATCH/create response vs frontend refetch | **frontend refetch** (simplest; timeline already invalidates) — optional `shifted_task_ids` can be added later | Frontend |
| D14 | Date editing UI | enable start/end editing in timeline vs keep create-only dates | **enable editing** (required for the demo/objective) | Frontend |
| D15 | Create with F-S violation | auto-shift the new task's dates vs reject (422) | **auto-shift** start (and end by same delta) to satisfy the chosen predecessor; document in response | Backend; tests |

## 8. Backend architecture

- **Extend `app/services/tasks.py`** with a pure scheduling function:
  `apply_schedule(tasks: list[Task], changed_ids: set) -> list[ScheduleShift]`
  - Input: all project tasks (one query, existing `get_project_tasks`).
  - Preconditions: dates already validated; graph acyclic (M7) or M7 runs first.
  - Algorithm: build `{task_id: depends_on_id}`; topological pass using the
    dependency order; for each task, `effective_start = max(task.start_date,
    pred.end_date + 1)`; if different, shift `start`/`end` by the delta
    (duration preserved), record a shift (task id, old/new start/end,
    caused_by predecessor id), and continue transitively.
  - Deterministic: process in a stable order (dependency level then
    `sort_order, created_at`); shifts only ever move forward (D1/D2), so the
    result is a fixed point independent of processing order.
  - Bounded: one pass over the task list per level; total work ≤ O(V·E) worst
    case but realistically O(V+E) for a flat, acyclic, single-predecessor list;
    cycles are rejected before scheduling.
  - Idempotent: re-running the same inputs produces no further shifts (dates
    already satisfy the constraint); no delta accumulation, no double-shift.
- **Wire into `app/api/v1/tasks.py`** inside `_assert_can_write`'s transaction
  (the project row lock is already held):
  - `create_task`: after adding the task, run `apply_schedule` over all project
    tasks (the new task may itself need an F-S adjustment — D15) and apply any
    shifts to dependents.
  - `update_task`: after applying the user's change and the existing M7
    validation, run `apply_schedule`; apply shifts to dependents.
  - `delete_task`: FK `SET NULL` clears edges; run `apply_schedule` (no-op
    expected) to keep the invariant code path uniform.
  - All ORM mutations + audits happen in the **one** locked transaction; commit
    is atomic; any validation failure rolls the whole schedule back.
- **No new endpoint, no new service layer, no worker/queue** (P4 postponed).

## 9. API changes

- **`PATCH /projects/{id}/tasks/{tid}`** — `depends_on_id` is **already
  writable**; M12 only adds the F-S cascade in the response behavior. No request
  shape change. Errors unchanged (400/422/404/403).
- **`POST /projects/{id}/tasks`** — unchanged request; F-S adjustment may alter
  the persisted dates (D15) without changing the contract.
- **`DELETE /projects/{id}/tasks/{tid}`** — unchanged; dependents' edges are
  cleared (FK) and dates preserved.
- **`GET /projects/{id}/tasks`** — unchanged response (frontend refetches after
  any mutation to see shifted dependents; D13).
- No new endpoints. Idempotency: PATCH is naturally idempotent (re-applying the
  same dates yields the same schedule); M8 claim-ledger semantics are unchanged
  and task endpoints remain outside M8 protection as today (M8 note: POST tasks
  idempotency was deferred — unchanged).

## 10. Frontend changes (minimum)

- **Dependency picker** in the add-task form and per-task: a select of the
  project's other tasks (excluding self); sends `depends_on_id` on create/PATCH.
- **Predecessor display**: show the predecessor's name/edge on each bar; a
  small "depends on X" tag.
- **Date editing**: start/end date inputs per task (writable only when
  `canWrite`); PATCH sends the dates. (D14)
- **Shift notice**: after a mutation whose response/refetch shows moved dates,
  show a transient "N tasks shifted" banner (derive by comparing refetched
  dates to pre-mutation dates client-side).
- **Read-only enforcement**: all new controls gated by `canWrite` (existing
  `isClient`/role gating in `ProjectDetail`); clients keep the current
  read-only timeline.
- **No new UI library** — extend the existing bar component.

## 11. RBAC / security

- Admin and assigned supervisor may create/update/delete tasks and edit
  dependencies/dates (unchanged `write_roles` + `_assert_can_write`).
- Procurement: unchanged (no task write; task read via `assert_can_view_project`).
- Client: **read-only** — timeline read via `assert_can_view_project`, all
  write/dependency/date controls hidden AND rejected 403 server-side (M6
  contract preserved; existing client tests remain).
- Google-authenticated users (M11) take the identical RBAC path (role-based,
  session-based) — no separate handling.
- Project assignment isolation and archived-project 404 behavior are inherited
  from `assert_can_view_project` / `assert_project_writable`; scheduling cannot
  bypass task authorization because it runs inside the already-authorized write
  path, and dependency changes require exactly the same authorization as task
  updates (PATCH route). IDOR: `depends_on_id` is validated to be same-project;
  schedule traversal is project-scoped.

## 12. Concurrency / transaction design

- The project row lock (`get_project_for_update` in `_assert_can_write`) is the
  single serialization point for all task writes in a project — M12 reuses it;
  concurrent task updates in the same project serialize; different projects are
  unaffected.
- All affected tasks are loaded in one query (`get_project_tasks`) within the
  locked transaction; the whole schedule (user change + dependents + audits) is
  flushed and committed atomically.
- Dependency chains are traversed in-transaction via the in-memory predecessor
  map; no nested queries (no N+1).
- Prevention of double-shifting: the algorithm is constraint-based (shift only
  if F-S violated), not delta-based; idempotent; a second identical mutation
  yields no additional shift.
- Partial-update safety: M7's validate-before-mutate pattern is preserved; if
  scheduling or audit fails, the single transaction rolls back — no partial
  schedule.
- No Redis/queues/workers (P4 postponed); the workload is one small in-memory
  pass per write.

## 13. Audit design

- The user-requested change keeps the existing `create`/`update`/`delete` rows
  for the edited task (unchanged, same transaction).
- Each **automatically shifted dependent** gets its own `task_schedule_shift`
  row (D12) with `changes` including `start_date`/`end_date` old/new and
  `caused_by_task_id` (the upstream task whose change triggered the shift),
  actor = the requesting user, `table_name="tasks"`, `record_id` = the shifted
  task id. All rows commit atomically with the schedule.
- No second audit system; `record_audit` only. Action name length ≤ varchar(100)
  (fits).

## 14. Database / migration analysis

- `depends_on_id` **already exists** (UUID, nullable) with FK
  `tasks.id ON DELETE SET NULL`; `project_id` FK CASCADE + index exists;
  `start_date`/`end_date` DATE non-null; `sort_order` exists.
- No missing columns, FK, or constraint needed for single-predecessor F-S
  scheduling. An index on `depends_on_id` is unnecessary (flat lists, one-query
  load).
- **NO DATABASE MIGRATION REQUIRED.**

## 15. Test strategy

A. **M7 regressions (existing — keep green):** date-order create/PATCH
   (full + partial), self-dependency, direct + indirect cycles, same-project
   existence, cycle-broken-by-delete.

B. **Basic scheduling (new):** A→B with B shifted when A's end moves later;
   3-node A→B→C; 10-node chain; no-dependency → no cascade; upstream moves
   earlier → no backward pull.

C. **Date changes (new):** end/start moves; duration change; dependency
   changed to a later predecessor; dependency removed (dates kept); create with
   F-S violation auto-shift (D15).

D. **Edge cases (new):** same-day predecessor; zero-length successor shift;
   fan-out (one predecessor, many dependents); missing/deleted dependency
   (FK SET NULL); archived project (404 for non-admin writes);
   unauthorized/clients (403); self-dependency re-check.

E. **Idempotency (new):** identical PATCH twice → same final dates, no second
   shift; re-running the scheduler over an already-consistent project changes
   nothing.

F. **Concurrency (new, real separate DB sessions):** two concurrent PATCHes of
   tasks in the same project (e.g., one moving an upstream, one moving a
   dependent) → deterministic final state (row lock serializes; both commits
   consistent, no lost update / no double-shift).

G. **Regression (required):** full backend suite (223+), migration suite,
   frontend `npm run build` + `npm run lint`, CI baseline-delta gates
   (ruff 2 / mypy 10 / oxlint 1 unchanged).

Clearly separate: A = existing tests; B–F = new M12 tests (extend
`test_tasks.py`; scheduling unit tests in a new `test_task_scheduling.py` if
cleaner).

## 16. Performance considerations

- Complexity: single in-memory pass over the project's tasks (target scale
  ~10–15 projects, tens of tasks each). Worst case bounded by O(V·E) (each
  task re-checked per dependency level); realistically O(V+E). Iterative, no
  recursion, bounded by task count.
- One SQL query to load the project's tasks inside the existing locked
  transaction; no N+1; no worker; no new infra.
- Lock duration: the row lock is already held for the write; the added pass is
  negligible at this scale. No over-engineering.

## 17. Regression risks

- Breaking M7 cycle/date validation → keep M7 checks first; run M7 tests.
- Changing PATCH semantics (dates now authoritative) could surprise existing
  callers → only forward shifts; clients/read-only untouched; document the
  behavior.
- Audit noise from shift rows → scoped to shifted dependents, same transaction.
- Frontend refetch/lost focus on date edit → controlled by `canWrite` and
  mutation-based updates; minor UX polish.
- Concurrency: mitigated by the project row lock + atomic single transaction.

## 18. Rollback strategy

- App-only (no migration): revert `services/tasks.py` + `api/v1/tasks.py`
  scheduling wiring and the frontend timeline changes; M7 data and schema are
  untouched; existing tasks/dependencies remain valid.
- No DB downgrade needed. If a shifted-dates data concern ever arises, a
  `git revert` of the scheduling commit restores the prior PATCH semantics.

## 19. Render smoke-test plan

1. Login as supervisor (password or Google — same path).
2. Open a project; create Task A (Foundation) and Task B (Framing).
3. Make B depend on A via the dependency picker.
4. Edit A's end date forward (later).
5. Verify B automatically shifts so B.start = A.end + 1; verify any 3rd
   dependent (Task C → B) shifts too.
6. Move A's end date backward (earlier) → verify B does **not** move (push-only).
7. Refresh the page → dates persist (server-authoritative).
8. Login as client → updated timeline visible, read-only; dependency/date
   controls absent; direct API PATCH → 403.
9. No Phase 4 infrastructure required (runs on the existing Render app).

## 20. Acceptance criteria

- F-S enforced server-side; every task mutation leaves the schedule
  dependency-consistent.
- Upstream forward change cascades to all transitive dependents (deterministic,
  idempotent, atomic).
- M7 date-order/cycle/same-project validations unchanged and green.
- Admin/supervisor write + client read-only RBAC unchanged (M6/M9/M11 intact).
- All new + existing tests pass; full suite green; ruff/mypy/oxlint baselines
  unchanged; frontend build/lint clean.
- No migration; no new dependency; no Phase 4 dependency.

## 21. Expected files

- `backend/app/services/tasks.py` (scheduling pass + shift records)
- `backend/app/api/v1/tasks.py` (call scheduler in create/update/delete;
  audit shifted dependents)
- `backend/tests/test_tasks.py` (extend) + `backend/tests/test_task_scheduling.py` (new)
- `frontend/src/components/ProjectTimeline.tsx` (dependency picker, date
  editing, shift notice, predecessor display)
- `frontend/src/types/index.ts` (Task types unchanged or minor)
- `frontend/src/lib/api.ts` (task update wrapper already supports depends_on_id)
- `docs/M12_IMPLEMENTATION_PLAN.md` (this) and `docs/M12_IMPLEMENTATION_REVIEW.md` (later)
- `docs/CURRENT_STATE.md`, `docs/ROADMAP.md`, `docs/SESSION_NOTES.md`

## 22. Documentation changes

- Update CURRENT_STATE (M12 section, test counts), ROADMAP (M12 DONE + PRD
  4.1.2 partial), SESSION_NOTES (M12 summary).
- Create `docs/M12_IMPLEMENTATION_REVIEW.md` after implementation recording:
  implementation summary, files changed, migration revision (**none**), API
  behavior, scheduling semantics, concurrency behavior, RBAC/security review,
  audit behavior, frontend behavior, test results, migration verification,
  frontend build/lint, ruff/mypy/CI baseline comparison, Render smoke-test
  results, security review, documentation updates, remaining concerns, and a
  final verdict of **SAFE TO COMMIT / NOT SAFE TO COMMIT**.

## 23. Non-goals

- Vendor/schedule **notifications** (separate gap; may need email infra).
- Non-working-day / holiday calendars; resource leveling; critical-path
  analysis; auto-balancing workloads.
- Multiple (many-to-many) predecessors.
- Offline support; drag-and-drop Gantt library; new charting dependency.
- Any Phase 4 infrastructure (workers, Redis, queues, observability).
- Changing task authorization, M6/M9/M11, or M8 idempotency semantics.

## 24. Implementation sequence

1. `services/tasks.py`: add `apply_schedule` + shift-record type; pure, tested.
2. Unit tests for `apply_schedule` (chains, fan-out, forward-only, idempotent).
3. `api/v1/tasks.py`: call scheduler in create/update/delete inside the locked
   transaction; audit `task_schedule_shift` rows; integration tests.
4. Concurrency tests (real separate sessions).
5. Frontend: dependency picker + date editing + predecessor display + shift
   notice; build/lint.
6. Full suite + migration tests + CI gates.
7. Docs + Render smoke.

## 25. Review/verification plan

- Focused: `pytest tests/test_tasks.py tests/test_task_scheduling.py`.
- Full: `pytest -q` (223+ incl. migrations).
- Gates: `npm run build`, `npm run lint`, ruff/mypy/oxlint baseline-delta,
  `git diff --check`.
- Render smoke per §19.
- `docs/M12_IMPLEMENTATION_REVIEW.md` with objective SAFE/NOT-SAFE criteria
  (all above green + no new findings + no infra dependency).

## 26. Commit/push checklist (after implementation)

- [ ] No secrets; `.env` untouched.
- [ ] Only intended files; `git diff --check` clean.
- [ ] Focused + full tests green; frontend build/lint green.
- [ ] No migration; Alembic head unchanged.
- [ ] Review doc updated with verified results and verdict.
- [ ] Commit/push only when explicitly requested.

## 27. Open questions / owner decisions

D1 cascade mode · D2 direction · D3 F-S boundary · D4 override policy ·
D5 dependency removal · D6 duration change · D7 multiple predecessors ·
D8 non-working days · D9 trigger timing · D10 recalculate endpoint ·
D11 migration/index · D12 shift audit action · D13 response metadata ·
D14 date-editing UI · D15 create-time F-S handling. (Recommendations and
rationale in §7.)

---

## Plan Self-Review Findings

**Confirmed strengths**
- M7 constraints fully preserved (date-order, self/same-project/cycle
  validation run first; project row lock reused).
- RBAC preserved: admin/assigned-supervisor write, procurement unchanged,
  client read-only server-enforced (M6 tests remain).
- M8 idempotency preserved (PATCH naturally idempotent; claim-ledger semantics
  untouched); no new endpoint.
- Algorithm deterministic (forward-only constraint-based fixed point, stable
  ordering) and idempotent (no cumulative double-shift).
- Cycles remain impossible (M7 gate before scheduling).
- Concurrency safe (single locked transaction; all project tasks in one query).
- No unnecessary API/DB/frontend scope: no migration, no new endpoint, no new
  library, single-predecessor model kept.
- No dependency on postponed Phase 4 infra (no workers/Redis/queues).
- Rollback is app-only and clean; tests are sufficient (M7 regressions +
  scheduling/idempotency/concurrency); Render demo is straightforward.

**Unresolved owner decisions** — D1–D15 (§7), chiefly cascade mode (D1/D2/D4),
F-S boundary (D3), shift audit action (D12), and create-time handling (D15).

**Risks** — scheduling UX complexity; surprise from PATCH now auto-adjusting
dependents; audit-row growth; frontend refetch-focus polish. All mitigated by
push-only semantics, atomic transactions, and scoped tests.

**Unnecessary scope removed** — vendor notifications, calendars, multi-
predecessor, critical-path, new charting library, new endpoints, any migration.

**Recommendation** — approve D1/D2/D3/D4/D12/D15 per the recommendations, keep
single-predecessor and no-migration, and proceed with the sequence in §24.
