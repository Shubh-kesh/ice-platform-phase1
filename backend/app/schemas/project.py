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
    admin transition endpoints) and `budget_spent` (M4: derived from the
    job-cost ledger — never hand-writable, or the invariant
    budget_spent == SUM(job_costs) breaks).
    """
    name: str | None = None
    site_address: str | None = None
    client_name: str | None = None
    start_date: date | None = None
    target_end_date: date | None = None
    budget_total: float | None = Field(default=None, ge=0)
    timeline_health: HealthStatus | None = None
    budget_health: HealthStatus | None = None
    safety_health: HealthStatus | None = None
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