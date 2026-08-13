"""Pydantic request/response contracts for in-app notifications (Phase 3, M13)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    type: NotificationType
    title: str
    body: str
    link: str | None
    read_at: datetime | None
    created_at: datetime


class UnreadCountRead(BaseModel):
    count: int
