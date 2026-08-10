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


class CostCode(str, enum.Enum):
    """Standard construction cost-code dimension for job-cost roll-ups.

    Trade/site-of-spend level (PRD example: "Masonry", "Plumbing"), plus a few
    general buckets (labor / material / equipment / other) so every expense
    can always be tagged. Extend here + with a migration when new codes are
    needed — the enum name is shared across the DB type and API schema.
    """
    FOUNDATION = "foundation"
    STRUCTURE = "structure"
    MASONRY = "masonry"
    ROOFING = "roofing"
    ELECTRICAL = "electrical"
    PLUMBING = "plumbing"
    HVAC = "hvac"
    FINISHING = "finishing"
    LANDSCAPING = "landscaping"
    LABOR = "labor"
    MATERIAL = "material"
    EQUIPMENT = "equipment"
    OTHER = "other"


class JobCost(Base):
    """A single costed line item against a project (labor, material, etc.).

    amount is always positive; the project's budget_spent is derived from the
    SUM of these rows (kept as a denormalized running total in the same
    transaction, mirroring inventory's quantity_on_hand pattern).
    """
    __tablename__ = "job_costs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    cost_code: Mapped[CostCode] = mapped_column(
        Enum(CostCode, name="cost_code"), nullable=False
    )
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
