"""
Schema scaffold for Financial & Accounting Integration (ICE pillar 3).

These tables are safe to migrate and use for internal job-costing and
milestone invoicing today. The QuickBooks/Xero *sync* itself is NOT
implemented here — that requires an OAuth app registration and sandbox
credentials from the business owner before any connector code can be
written or tested meaningfully. See PHASE2_PROGRESS.md for what's needed
to unblock that piece. external_ref/external_sync_status exist now so the
sync worker (once built) has somewhere to record its state without another
migration.
"""
import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Enum, String, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class ExternalSyncStatus(str, enum.Enum):
    NOT_SYNCED = "not_synced"
    SYNCED = "synced"
    SYNC_FAILED = "sync_failed"


class JobCost(Base):
    """A single costed line item against a project (labor, material, etc.)."""
    __tablename__ = "job_costs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)  # labor, material, equipment, other
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    incurred_on: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship()  # noqa: F821


class Invoice(Base):
    """A milestone-based client invoice. external_* fields are placeholders
    for the QuickBooks/Xero connector — unused until that's built."""
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    milestone_name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status"), default=InvoiceStatus.DRAFT, nullable=False
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_sync_status: Mapped[ExternalSyncStatus] = mapped_column(
        Enum(ExternalSyncStatus, name="external_sync_status"),
        default=ExternalSyncStatus.NOT_SYNCED,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship()  # noqa: F821
