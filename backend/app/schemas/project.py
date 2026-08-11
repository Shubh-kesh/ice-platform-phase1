import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import ProjectStatus, HealthStatus


class ProjectBase(BaseModel):
    name: str
    site_address: str
    client_name: str
    start_date: date
    target_end_date: date
    budget_total: float = Field(ge=0)


class ProjectCreate(ProjectBase):
    """Admin creates a DRAFT project; project_code is auto-generated server-side."""


class ProjectUpdate(BaseModel):
    """Editable fields for an existing project.

    Deliberately excludes `status` (lifecycle moves only via the dedicated
    admin transition endpoints), `budget_spent` (M4: derived from the
    job-cost ledger — never hand-writable, or the invariant
    budget_spent == SUM(job_costs) breaks), and the manual health columns
    (M3: health now comes from computation or an audited admin override —
    never PATCH-able).
    """
    name: str | None = None
    site_address: str | None = None
    client_name: str | None = None
    start_date: date | None = None
    target_end_date: date | None = None
    budget_total: float | None = Field(default=None, ge=0)
    percent_complete: int | None = Field(default=None, ge=0, le=100)


class AssignmentCreate(BaseModel):
    """Assign an existing user to a project (admin-only endpoint)."""

    user_id: uuid.UUID


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_code: str
    status: ProjectStatus
    timeline_health: HealthStatus
    budget_health: HealthStatus
    safety_health: HealthStatus
    budget_spent: float
    percent_complete: int
    created_by: uuid.UUID | None
    completed_at: datetime | None
    completed_by: uuid.UUID | None
    archived_at: datetime | None
    archived_by: uuid.UUID | None
    restored_at: datetime | None
    restored_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectReadRestricted(BaseModel):
    """Site-supervisor view — the M3 no-money slice.

    Identical to ProjectRead except that the monetary fields
    (budget_total/budget_spent) are omitted: supervisors never receive
    internal budget figures through a project response. The deprecated
    manual health colors stay (they carry no money). Supervisors do keep the
    lifecycle attribution columns (internal to the operations team); the
    CLIENT gets the tighter ProjectClientRead shape (M6).
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_code: str
    name: str
    site_address: str
    client_name: str
    start_date: date
    target_end_date: date
    status: ProjectStatus
    timeline_health: HealthStatus
    budget_health: HealthStatus
    safety_health: HealthStatus
    percent_complete: int
    created_by: uuid.UUID | None
    completed_at: datetime | None
    completed_by: uuid.UUID | None
    archived_at: datetime | None
    archived_by: uuid.UUID | None
    restored_at: datetime | None
    restored_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectClientRead(BaseModel):
    """CLIENT view — the M6 client-portal contract.

    The only shape a CLIENT ever receives for a project. Deliberately
    excludes every internal operations field: budget figures, the deprecated
    manual health columns, lifecycle attribution (who did what), archive/
    restore bookkeeping, and internal created/updated timestamps. A client
    sees their project name/code, site address, schedule, status and progress
    — nothing more. Enforced server-side (never frontend hiding); clients
    never see ARCHIVED projects (404, M10).
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_code: str
    name: str
    site_address: str
    client_name: str
    start_date: date
    target_end_date: date
    status: ProjectStatus
    percent_complete: int
    completed_at: datetime | None