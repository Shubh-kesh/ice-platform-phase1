M10 — Project Lifecycle & Admin is complete. Summary of what was done this session:
Backend
- Migration d7e9f1a2b3c4: unique project_code, created_by, completed/archived/restored_at/by columns, project_status enum extended with DRAFT/ARCHIVED. Applied + verified on the dev DB (15/15 rows backfilled, valid codes).
- app/services/projects.py: PRJ-YYYY-#### code generator (max-seq + unique-constraint retry).
- POST /projects (admin) → auto-code + DRAFT status, created_by set; ProjectUpdate no longer accepts status/budget_spent.
- Admin-only, audited transition endpoints: activate, complete, archive, restore — legal transitions enforced (400 otherwise), lifecycle timestamps/actors recorded per rule, audit row in the same transaction, no hard-delete path.
- project_access.py: get_project_or_404 + can_access_archived; archived project = 404 for non-admins (no existence leak), excluded from lists unless ?include=archived.
- Seed gating: demo data only loads with ICE_SEED_DEMO=true.
Frontend
- Types extended (draft/archived, project_code, lifecycle fields); api.ts helpers.
- Command Center: admin "New site" modal + "Show archived" toggle; ProjectCard shows the code + per-status badge; ProjectDetail: lifecycle action menu (legal-from-status, admin) + archival banner + lifecycle date rows, child panels freeze when archived.
Quality — 69/69 backend tests (12 new lifecycle tests: transitions chain, RBAC, invalid-transition 400s, archive filtering/404, audit, codegen uniqueness, descendants + budget_spent invariant across archive/restore). Frontend tsc+vite build and oxlint clean; ruff/mypy report only pre-existing errors (current_state §6 updated).
Docs updated (CURRENT_STATE.md, ROADMAP.md, SESSION_NOTES.md). Work is uncommitted — not in git. Two known notes: transitions are not row-locked yet (documented hardening item), and docs/ROADMAP.md M3 is now the next milestone.