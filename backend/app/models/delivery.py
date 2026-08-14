"""
PO delivery / receipt records (Phase 5, M15).

A `deliveries` row is a single verified receipt event against an APPROVED (or
PARTIALLY_RECEIVED) purchase order — the evidence header (reference / note /
photo_reference + verification attribution). `delivery_lines` are the
per-PO-line quantities received, each snapshotting the unit price and derived
line total at receipt time so later PO edits can never alter receipt history.

Both are append-only financial evidence: no update/delete endpoints exist. The
M15 receiving flow derives inventory release (RECEIVED stock movements via
`stock_movements.po_line_id`) and cost release (JobCost rows via
`job_costs.po_line_id`) from these records. `po_lines.received_quantity`
accumulates across receipts; a delivery line never over-receives its PO line
(app-level, over-receiving doctrine).
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Delivery(Base):
    """A single verified receipt event against a purchase order."""

    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_deliveries_purchase_order_id", "purchase_order_id"),
        Index("ix_deliveries_project_id", "project_id"),
        Index("ix_deliveries_verified_at", "verified_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lines: Mapped[list["DeliveryLine"]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan"
    )


class DeliveryLine(Base):
    """A single PO line received as part of a delivery.

    `unit_price` and `line_total` are server-derived snapshots (ROUND_HALF_UP,
    2dp) taken from the PO line at receipt time — receipts are immutable
    financial evidence, so the amounts never change with later PO edits.
    """

    __tablename__ = "delivery_lines"
    __table_args__ = (
        Index("ix_delivery_lines_delivery_id", "delivery_id"),
        Index("ix_delivery_lines_po_line_id", "po_line_id"),
        Index("ix_delivery_lines_inventory_item_id", "inventory_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False
    )
    po_line_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("po_lines.id", ondelete="RESTRICT"), nullable=False
    )
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    delivery: Mapped["Delivery"] = relationship(back_populates="lines")
