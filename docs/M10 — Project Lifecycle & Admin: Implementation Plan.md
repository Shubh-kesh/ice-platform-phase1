M10 — Project Lifecycle & Admin: Implementation Plan
Objective
Make projects administratively real and database-driven: admin creates projects with auto-generated unique codes; explicit DRAFT → ACTIVE → COMPLETED → ARCHIVED lifecycle with no hard-deletes; every transition audited (who/when); archived hidden from normal lists but retained in reporting; seed/demo data gated behind a dev flag.
Why it comes here
It's the foundation for M3 (health) and M5 (invoicing), both of which must operate on a lifecycle-aware project universe. The current enum is planning|active|on_hold|completed (models/project.py:12) and nothing prevents a supervisor from PATCH-ing a project to completed. M10 is small, low-blast-radius, and everything downstream consumes it.
Dependencies
- M2 assignments — unchanged; lifecycle must preserve project_assignments on ALL states.
- M4 job costs — budget_spent == SUM(job_costs) invariant must hold in all states; no manual budget override introduced.
- record_audit() (middleware/audit.py) — already transactional, reuse for transitions.
- project_access.py — extend assert_can_view_project for archived visibility.
1. Database change (new migration d7e9f1a2b3c4_m10_project_lifecycle.py)
On projects, add:
- project_code VARCHAR NOT NULL + unique index (backfill existing rows)
- created_by UUID NULL REFERENCES users(id) (backfill = admin-set or NULL)
- archived_at TIMESTAMPTZ NULL, archived_by UUID NULL
- completed_at TIMESTAMPTZ NULL, completed_by UUID NULL
- restored_at TIMESTAMPTZ NULL, restored_by UUID NULL
- Extend the project_status enum with draft + archived (Postgres ALTER TYPE ... ADD VALUE).
Open item for you: keep planning/on_hold or map them (e.g. planning → draft, on_hold → active)? My default: keep them for now to avoid a destructive data migration; lifecycle transitions operate on the new draft/archived edges.
2. Code generation (service layer — app/services/projects.py)
- Format PRJ-YYYY-#### (year + zero-padded sequence). Query the max code for the year via SELECT ... WHERE project_code LIKE 'PRJ-<year>-%' ORDER BY ... DESC LIMIT 1, increment, retry loop on unique-violation (race). Reserved: no manual code entry; uniqueness at DB + API 409.
3. Model + schema changes
- models/project.py: add the columns above; created_by/*_by/*_at relationships not required (store UUIDs).
- schemas/project.py:
- ProjectCreate — admin still provides name/address/client/dates/budget; project_code and status auto-set (DRAFT).
- ProjectUpdate — remove status, budget_spent from PATCH-able fields (see security). Supervisor PATCH stays limited to non-lifecycle, non-finance fields (dates/name/address).
- ProjectRead — add project_code, created_by, archived_at/by, completed_at/by, restored_at/by.
- New transition response models (ProjectLifecycleRead) or reuse ProjectRead with status changed.
4. API (api/v1/projects.py)
- POST /projects (admin): generate code, created_by=admin.id, status=DRAFT. (Existing endpoint can stay, extended.)
- GET /projects: default excludes ARCHIVED; admin can pass ?include=archived; completed/active unchanged. Keeps M4/RBAC intact.
- New admin-only lifecycle transitions, each: validate the transition is legal, set status + *_at/*_by, record_audit(action="complete"|"archive"|"restore"|"activate", changes={old→new}), single commit:
- POST /projects/{id}/activate (DRAFT→ACTIVE, also planning→active)
- POST /projects/{id}/complete (ACTIVE→COMPLETED; sets percent_complete=100)
- POST /projects/{id}/archive (COMPLETED→ARCHIVED; optionally ACTIVE→ARCHIVED)
- POST /projects/{id}/restore (ARCHIVED→ACTIVE or ARCHIVED→COMPLETED)
- GET /projects/{id}: read-allowed for COMPLETED; ARCHIVED requires admin (?include=archived semantics or 404/403 for non-admin).
- No DELETE endpoint exists and none is added.
5. project_access.py
- assert_can_view_project: admin/proc may view archived; supervisor/client get 403/404 on archived unless it's surfaced via explicit admin query. Non-admin GET of archived → 404 (don't leak existence).
6. Seed gating (seed.py)
- Wrap project+user seeding in if os.getenv("ICE_SEED_DEMO", "false").lower() == "true" (or a --demo CLI flag). Production default: off. Existing dev DBs keep data; new installs start empty. Update docker-compose/docs accordingly.
7. Frontend
- types/index.ts: ProjectStatus + code + lifecycle fields; ProjectCreateInput.
- CommandCenter.tsx: admin "Create Project" modal; admin-only archive filter toggle; render project_code on cards. Backend already filters archived — the UI reflects this.
- ProjectCard.tsx: show code + status; lifecycle badge for archived/completed.
- ProjectDetail.tsx: new admin-only Lifecycle actions menu (Activate / Complete / Archive / Restore) calling the transition endpoints; invalid transitions hidden (e.g. no "Complete" on DRAFT).
- ProjectAssignments.tsx: unchanged (still visible on all states; block writing assignments on ARCHIVED).
8. Security
- Lifecycle transitions admin-only (require_role(ADMIN)) and fully audited.
- Remove status/budget_spent from public ProjectUpdate — closes the supervisor-can-complete hole and protects the M4 cash invariant.
- ARCHIVED is read-only and hidden by default; never a hard-delete; responses never leak financial fields to client (already enforced for job-cost/budget — keep it).
- Code uniqueness + format enforced at DB and API.
9. Tests — tests/test_project_lifecycle.py
1. Create → DRAFT + valid PRJ-YYYY-#### code; second create → unique, incremented.
2. Valid chain DRAFT→ACTIVE→COMPLETED→ARCHIVED→RESTORE succeeds; each transition has an audit row with correct actor.
3. Invalid transitions rejected (e.g. DRAFT→ARCHIVED directly, or re-archive) — 400.
4. Non-admin (supervisor/client) transitions → 403; supervisor PATCH attempting status → 400/ignored.
5. ARCHIVED absent from GET /projects for all; present with ?include=archived (admin); non-admin GET of archived project → 404.
6. Child data (job costs, inventory, site logs, assignments) intact after COMPLETE & ARCHIVE; budget_spent == SUM(job_costs) still holds.
7. PATCH budget_spent rejected.
10. Acceptance criteria
- Admin creates projects with unique auto codes; lifecycle walkable only through audited admin actions; archived hidden but in reporting; no hard-delete; seed runs only with demo flag; M4 invariant preserved; existing 57 tests + new suite green; tsc/vite + ruff/mypy clean.
Sequencing (matches roadmap): M10 → M3 → M5 → M6 → M7/M8 → M9 → M11.