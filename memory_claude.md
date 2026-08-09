Purpose & context

Shubhansh is building a comprehensive construction management platform called the Intelligent Construction Engine (ICE), designed to manage 15 simultaneous residential construction projects. The platform has four core functional pillars:

Multi-Site Project Tracking: Command center dashboard with color-coded health indicators and dynamic Gantt charts
Integrated Inventory & Procurement: Live stock tracking across multiple locations with QR-code verification
Financial & Accounting Integration: Real-time job costing, milestone-based invoicing, QuickBooks/Xero sync
Quality & Safety: Digital inspection checklists with hold-point gating

Three AI/ML features are also planned: Computer Vision quality control, predictive delay modeling, and automated Bill of Quantities generation from architectural PDFs.

Confirmed tech stack: Python (FastAPI) backend, React with TypeScript frontend, PostgreSQL + Redis for data storage, GCP deployment with CI/CD pipeline. Design reference: sparkbuild.in.

Current state

Development is underway collaboratively with Claude providing code step by step. Phase 1 (foundation) is partially complete within a monorepo at /home/claude/ice-platform. Completed so far:

Full directory structure scaffolded
Backend dependency files and core configuration (pydantic-settings)
Async SQLAlchemy database engine
Security utilities (bcrypt + JWT)
ORM models: User (roles: admin, site_supervisor, procurement_manager, client), Project (health status enums), ProjectAssignment, AuditLog
Pydantic schemas for auth, users, and projects
FastAPI routers: authentication (login, token refresh, /me), user management (admin-only CRUD), projects (role-scoped visibility)
Reusable RBAC dependency factory
Audit trail middleware helper

Still remaining in Phase 1:

Main FastAPI app entrypoint
Alembic migration setup
Docker configuration
GCP and CI/CD infrastructure files

On the horizon

Complete Phase 1 foundation before advancing
Subsequent phases include multi-site dashboard, inventory/procurement, financial integration, and AI/ML features
Full 8-month build timeline planned across five phases

Approach & patterns

Collaborative build model: Shubhansh drives requirements and decisions; Claude provides incremental, step-by-step code
Architecture prioritizes scalability, visual attractiveness, and security from the ground up
Role-based access control (RBAC) is a first-class concern, baked into the foundation layer
Audit logging is treated as a core infrastructure concern, not an afterthought