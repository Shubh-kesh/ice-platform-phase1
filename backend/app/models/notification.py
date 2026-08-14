import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationType(str, enum.Enum):
    TASK_SCHEDULE_SHIFT = "task_schedule_shift"
    MILESTONE_INVOICE_ISSUED = "milestone_invoice_issued"
    INVENTORY_LOW_STOCK = "inventory_low_stock"
    PROJECT_ASSIGNED = "project_assigned"
    PO_SUBMITTED = "po_submitted"
    PO_APPROVED = "po_approved"
    PO_REJECTED = "po_rejected"
    PO_RECEIVED = "po_received"


class Notification(Base):
    """A single in-app notification owned by exactly one user (M13).

    Created atomically with the business event that triggered it. Content is
    deliberately minimal (title/body/link) — never secrets, tokens, or data a
    recipient is not otherwise authorized to see.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # Feed + unread-count lookups.
        Index("ix_notifications_user_read", "user_id", "read_at"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    # Constrained string (app-level enum) — keeps alembic free of native-enum
    # migration pitfalls while constraining values in the ORM.
    type: Mapped[NotificationType] = mapped_column(
        String(50), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String(2000), nullable=False)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Notification {self.type.value} -> {self.user_id} read={self.read_at is not None}>"
