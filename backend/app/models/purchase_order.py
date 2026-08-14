"""
Purchase orders + PO line items (Phase 5, M14).

A PO is a project-scoped *commitment* document (vendor, lines, quantities,
prices, cost codes, status) — NOT an expenditure. M14 creates no job-cost rows
and no stock movements; delivery verification / receiving is a later Phase 5
milestone (M15), after which the M4 cost_code on each line tags the material
cost correctly.

Lifecycle (audited, row-locked transitions only — no status PATCH):

    DRAFT -> PENDING_APPROVAL -> APPROVED   (approved/cancelled terminal in M14)
    DRAFT|PENDING_APPROVAL -> CANCELLED
    PENDING_APPROVAL -> REJECTED -> (DRAFT via revise | PENDING_APPROVAL via resubmit)

`total_amount` is a denormalized running total (subtotal + tax) recomputed in
the same transaction as every line/header mutation — the M4 budget_spent /
M1 quantity_on_hand pattern. `po_number` (PO-{project_code}-{seq:04d}) is
allocated under the project row lock so concurrent creates serialize, with
`uq_purchase_orders_po_number` as the DB backstop.
"""
import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.finance import CostCode


class POStatus(str, enum.Enum):
    """Purchase-order lifecycle (M14 + M15).

    APPROVED and CANCELLED were terminal in M14. M15 adds PARTIALLY_RECEIVED
    and RECEIVED via an additive ALTER TYPE: receiving derives them from the
    lines' accumulated `received_quantity`. Values are stored by member name
    (DRAFT/PENDING_APPROVAL/...) in the native enum, matching the M5
    invoice_status pattern. RECEIVED is terminal; no `closed` state exists.
    """
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("po_number", name="uq_purchase_orders_po_number"),
        Index("ix_purchase_orders_project_id", "project_id"),
        Index("ix_purchase_orders_vendor_id", "vendor_id"),
        Index("ix_purchase_orders_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    po_number: Mapped[str] = mapped_column(String(40), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[POStatus] = mapped_column(
        Enum(POStatus, name="po_status"), default=POStatus.DRAFT, nullable=False
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_delivery: Mapped[date | None] = mapped_column(Date, nullable=True)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lines: Mapped[list["POLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class POLine(Base):
    """A single PO line item.

    `line_total` is derived ON READ (quantity x unit_price, ROUND_HALF_UP to
    2dp) and never stored. `cost_code` reuses the M4 enum so the M15 receiving
    flow can create the material JobCost with the correct cost code.
    `received_quantity` (M15) accumulates across verified receipts and can
    never exceed `quantity` (app-level, over-receiving doctrine); the balance
    `quantity - received_quantity` is derived on read. `inventory_item_id`
    records the item a line feeds (set on first receipt, app-immutable).
    """
    __tablename__ = "po_lines"
    __table_args__ = (
        Index("ix_po_lines_purchase_order_id", "purchase_order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False
    )
    inventory_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cost_code: Mapped[CostCode] = mapped_column(
        Enum(CostCode, name="cost_code"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")
