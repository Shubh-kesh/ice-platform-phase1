import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    """Read-only audit log entry."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str  # create | update | delete
    table_name: str
    record_id: str
    changes: dict
    ip_address: str | None
    created_at: datetime
