import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.task import TaskStatus


class TaskBase(BaseModel):
    name: str
    start_date: date
    end_date: date
    depends_on_id: uuid.UUID | None = None
    sort_order: int = 0

    @model_validator(mode="after")
    def check_date_order(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: TaskStatus | None = None
    percent_complete: int | None = Field(default=None, ge=0, le=100)
    depends_on_id: uuid.UUID | None = None
    sort_order: int | None = None


class TaskRead(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: TaskStatus
    percent_complete: int
    created_at: datetime
    updated_at: datetime
