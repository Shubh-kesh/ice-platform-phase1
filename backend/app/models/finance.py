"""
Schema for the Finance pillar (Phase 3): job costing (M4) and milestone
invoicing (M5).

The QuickBooks/Xero *sync* itself is NOT implemented here — that requires an
OAuth app registration and sandbox credentials from the business owner before
any connector code can be written or tested meaningfully. external_ref/
external_sync_status exist now so the sync worker (once built) has somewhere to
record its state without another migration.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Enum,
    String,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.project import Project


class InvoiceStatus(str, enum.Enum):
    """Milestone invoice/payment-request state (M5).

    OVERDUE is kept in the enum (legacy column) but is never stored by any
    endpoint — the read layer derives it (status == SENT and due_date passed)
    so it can't go stale.
    """
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


class BillingType(str, enum.Enum):
    """How a billing milestone's invoice amount is derived (M5)."""
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"


class BillingMilestoneStatus(str, enum.Enum):
    """Lifecycle of a billing milestone — COMPLETED is the eligibility gate
    for generating its invoice. No hard-delete path exists for milestones."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


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


class BillingMilestone(Base):
    """A schedule-of-values billing milestone (Phase 3, M5).

    This is the *billing/revenue* surface — deliberately independent of the
    job-cost ledger, which represents expenditure. The invoice amount derives
    from the milestone rule (percentage of Project.budget_total, or a fixed
    amount) at invoice-generation time; job costs never enter the calculation.

    Exactly one of billing_percentage / fixed_amount must be set (validated in
    the app layer). status gates invoice eligibility: only a COMPLETED milestone
    can generate an invoice, and completion records who/when for the audit trail.
    """
    __tablename__ = "billing_milestones"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "name", name="uq_billing_milestones_project_name"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    billing_type: Mapped[BillingType] = mapped_column(
        Enum(BillingType, name="billing_type"), nullable=False
    )
    billing_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    fixed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[BillingMilestoneStatus] = mapped_column(
        Enum(BillingMilestoneStatus, name="billing_milestone_status"),
        default=BillingMilestoneStatus.NOT_STARTED,
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship()
    invoice: Mapped["Invoice | None"] = relationship()  # noqa: F821


class Invoice(Base):
    """A milestone-based client invoice / payment request (Phase 3, M5).

    Amount is derived server-side from the referenced BillingMilestone at
    generation time — clients never supply money values. DRAFT -> SENT -> PAID
    (issue / mark-paid / cancel transitions are admin-only audited actions).
    Once a project is COMPLETED or ARCHIVED the invoice ledger is immutable
    (no creates, no transitions); there is no hard-delete path.

    external_* fields are placeholders for the QuickBooks/Xero connector —
    unused until that's built, and never serialized to clients.
    """
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("invoice_number", name="uq_invoices_invoice_number"),
        # At most one non-cancelled invoice per billing milestone — the DB-level
        # double-billing guard. Cancelling an invoice frees its milestone for a
        # re-issue. Enum values are stored by member name (SENT/CANCELLED/...).
        Index(
            "uq_invoices_one_non_cancelled_per_milestone",
            "billing_milestone_id",
            unique=True,
            postgresql_where=text(
                "billing_milestone_id IS NOT NULL AND status <> 'CANCELLED'"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    invoice_number: Mapped[str] = mapped_column(String(40), nullable=False)
    billing_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_milestones.id", ondelete="SET NULL"), nullable=True
    )
    milestone_name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoice_status"), default=InvoiceStatus.DRAFT, nullable=False
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

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
    billing_milestone: Mapped["BillingMilestone | None"] = relationship(
        viewonly=True
    )  # noqa: F821