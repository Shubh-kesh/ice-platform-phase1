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
    pass


class ProjectUpdate(BaseModel):
    name: str | None = None
    status: ProjectStatus | None = None
    timeline_health: HealthStatus | None = None
    budget_health: HealthStatus | None = None
    safety_health: HealthStatus | None = None
    percent_complete: int | None = Field(default=None, ge=0, le=100)
    budget_spent: float | None = None


class AssignmentCreate(BaseModel):
    """Assign an existing user to a project (admin-only endpoint)."""

    user_id: uuid.UUID


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: ProjectStatus
    timeline_health: HealthStatus
    budget_health: HealthStatus
    safety_health: HealthStatus
    budget_spent: float
    percent_complete: int
    created_at: datetime
    updated_at: datetime
