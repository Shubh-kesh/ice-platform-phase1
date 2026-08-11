import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.health import HealthOverrideTarget, HealthOverrideValue
from app.models.project import HealthStatus, ProjectStatus


class HealthDimensionRead(BaseModel):
    """One dimension: the computed verdict (with reasons) and the effective one
    (computed, unless an admin override applies). value/effective are NOT_RATED
    when the dimension cannot be rated — the grey state is explicit, never a
    hidden green."""
    value: HealthStatus
    effective: HealthStatus
    rated: bool
    reasons: list[str]
    data_sufficient: bool


class HealthOverallRead(BaseModel):
    """Worst-of-rated overall. basis names the dimensions that were actually
    rated so the UI can say 'based on Timeline, Budget (Safety not tracked)'."""
    value: HealthStatus
    effective: HealthStatus
    rated: bool
    reasons: list[str]
    basis: list[str]


class HealthOverrideSummaryRead(BaseModel):
    """A single override row from the health-override history (append-only)."""
    id: uuid.UUID
    project_id: uuid.UUID
    applied_to: HealthOverrideTarget
    value: HealthOverrideValue
    reason: str
    set_by: uuid.UUID | None
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    revoked_by: uuid.UUID | None
    active: bool


class HealthOverrideCreate(BaseModel):
    """Admin override of a computed verdict. NOT_RATED is deliberately not a
    valid target value — you cannot override a data shortage into a color."""
    applied_to: HealthOverrideTarget
    value: HealthOverrideValue
    reason: str = Field(min_length=10, max_length=2000)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ProjectHealthRead(BaseModel):
    """Health payload — never carries monetary figures, so it is safe for every
    role (supervisor/client see colors + reasons; admin/procurement also get the
    override history)."""
    project_id: uuid.UUID
    project_code: str
    status: ProjectStatus
    frozen: bool
    timeline: HealthDimensionRead
    budget: HealthDimensionRead
    safety: HealthDimensionRead
    overall: HealthOverallRead
    data_sufficiency: dict[str, bool]
    overrides: list[HealthOverrideSummaryRead]