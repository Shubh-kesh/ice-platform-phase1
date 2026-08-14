import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, String, DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MovementType(str, enum.Enum):
    RECEIVED = "received"    # stock delivered to site (+quantity)
    CONSUMED = "consumed"    # stock used in construction (-quantity)
    TRANSFERRED = "transferred"  # moved out to another site (-quantity)
    ADJUSTED = "adjusted"     # manual correction, e.g. recount found extra stock (+quantity)
    # Note: quantity submitted via the API is always a positive magnitude —
    # the endpoint applies the sign above. Downward corrections (damage,
    # loss) are recorded as CONSUMED with an explanatory note rather than a
    # signed ADJUSTED, keeping the ledger's sign convention unambiguous.


class InventoryItem(Base):
    """
    A material/SKU tracked at a specific project site. quantity_on_hand is
    a denormalized running total, kept in sync by StockMovement writes —
    trades reconciliation accuracy for simple, fast reads on the dashboard.
    QR-code scanning (Phase 2 stretch goal) would create StockMovement rows
    the same way a manual entry does; no schema change needed for that later.
    """
    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)  # bags, kg, m3, pcs, ...
    quantity_on_hand: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    reorder_threshold: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    unit_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship()  # noqa: F821
    movements: Mapped[list["StockMovement"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class StockMovement(Base):
    """
    Immutable ledger entry for a single inventory change. quantity is signed
    from the ledger's point of view (+received/adjusted-up, -consumed/
    adjusted-down) so InventoryItem.quantity_on_hand is just a running sum.
    """
    __tablename__ = "stock_movements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, name="movement_type"), nullable=False
    )
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("po_lines.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    item: Mapped["InventoryItem"] = relationship(back_populates="movements")
