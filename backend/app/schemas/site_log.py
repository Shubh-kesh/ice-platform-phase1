import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class DailySiteLogBase(BaseModel):
    log_date: date
    work_summary: str = Field(min_length=1)
    issues: str | None = None
    workers_present: int | None = Field(default=None, ge=0)
    weather: str | None = None


class DailySiteLogCreate(DailySiteLogBase):
    photo_urls: list[str] = Field(default_factory=list)


class DailySiteLogRead(DailySiteLogBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    created_by: uuid.UUID | None
    photo_urls: list[str]
    created_at: datetime
