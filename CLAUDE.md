# CLAUDE.md

Persistent development instructions for AI coding sessions on the ICE platform.

## Project Overview

INTELLIGENT CONSTRUCTION ENGINE (ICE) is an Intelligent Multi-Site Construction
ERP that manages ~10–15 residential construction projects simultaneously:
scheduling/Gantt, daily site logs, inventory, and finance in one dashboard.

Stack: React 19 + Vite SPA (TanStack Query, axios) · FastAPI (async SQLAlchemy,
asyncpg) · PostgreSQL 16 · Alembic · Docker Compose (dev). Redis is provisioned
but currently unused. Single-service monolith, no services/repositories layer.

## Project Context

Documentation maps (source code is always the ground truth):

- `docs/PRODUCT_REQUIREMENTS.md` — long-term product vision and requirements (what the product will become).
- `docs/CURRENT_STATE.md` — actual current implementation (what exists today, verified, incl. bugs/debt/limitations).
- `docs/ARCHITECTURE.md` — actual implemented architecture, with Mermaid diagrams and data flows.
- `docs/ROADMAP.md` — planned future development phases, priorities, and acceptance criteria.
- `docs/TECHNICAL_AUDIT.md` — prior comprehensive audit; source of known risks.

## Development Rules

1. Preserve existing Phase 1 and Phase 2 functionality.
2. Treat the source code as the source of truth for current implementation.
3. Read the relevant documentation before implementing major features.
4. Prefer incremental changes over large rewrites.
5. Do not modify unrelated modules.
6. Follow existing architectural patterns unless there is a documented reason to change them.
7. Add appropriate tests for new functionality.
8. Do not expose secrets, API keys, passwords, or production credentials.
9. Do not make destructive database changes without explicit approval.
10. Maintain proper authentication and authorization.
11. Maintain project-level data isolation.
12. Maintain auditability for financial operations.
13. Consider scalability for approximately 10–15 concurrent residential projects.
14. Do not implement future AI/ML capabilities unless explicitly requested.
15. Do not commit changes unless explicitly asked.

## Phase Development Rules

For every new phase:

1. Read ROADMAP.md.
2. Identify the specific milestone being implemented.
3. Inspect the existing implementation before changing it.
4. Explain the implementation plan.
5. Wait for approval before major changes.
6. Implement incrementally.
7. Run relevant tests.
8. Review for regressions.
9. Update CURRENT_STATE.md after successful completion.

## Environment & Commands

- Backend: `cd backend && pytest tests/ -v` (requires `docker compose up -d postgres`; run in `backend/`).
- Frontend: `cd frontend && npm run build` (tsc + vite), `npm run lint` (oxlint).
- Checks are NOT CI-gated: run ruff / mypy / tsc / tests before finishing work.

## Key Conventions

- Money = `Numeric(14,2)`; quantity = `Numeric(12,2)`; UUID PKs; Postgres-native types (JSONB, ENUM).
- Inventory: immutable signed `stock_movements` ledger is source of truth; `quantity_on_hand` is a denormalized running total updated in the same transaction.
- `audit_logs` and `daily_site_logs` are append-only (no update/delete endpoints).
- Mutations record audit via `record_audit()` in the same transaction as the change.
- RBAC: admin/procurement see all projects; supervisor/client only assigned ones (`assert_can_view_project`).
- All project-scoped reads/writes go through `app/api/project_access.py`.