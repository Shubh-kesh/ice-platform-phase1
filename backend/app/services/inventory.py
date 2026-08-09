"""
Thin services layer for inventory integrity logic — the first module outside
the route handlers (per the Phase 3 architecture direction of separating core
domain logic from request handling).

These functions are deliberately pure: no request/dependency objects, no
authorization, no audit calls. Routes own those concerns; this module owns the
domain math, so it can be unit-tested in isolation.
"""
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import InventoryItem, MovementType, StockMovement

# Sign convention applied to every movement — the ledger's point of view.
# Received/adjusted add stock; consumed/transferred remove it. A dedicated
# ADJUSTED enum value exists so corrections are explicit, never silent.
MOVEMENT_SIGN = {
    MovementType.RECEIVED: 1,
    MovementType.ADJUSTED: 1,
    MovementType.CONSUMED: -1,
    MovementType.TRANSFERRED: -1,
}


def _ledger_sign() -> Any:
    """SQL expression: +1 for stock-increasing types, -1 for stock-decreasing."""
    return case(
        (StockMovement.movement_type.in_([MovementType.RECEIVED, MovementType.ADJUSTED]), 1),
        else_=-1,
    )


async def reconcile_project_inventory(
    db: AsyncSession, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    """
    Recompute each item's on-hand balance from the immutable ledger and compare
    it against the denormalized `quantity_on_hand` running total.

    Returns one entry per item in the project: the ledger-derived balance, the
    stored running total, and whether they agree. A mismatch (matches=False)
    means the running total diverged from the ledger — typically a legacy
    lost-update race — and should be corrected with an ADJUSTED movement rather
    than a silent column write.
    """
    stmt = (
        select(
            InventoryItem.id.label("item_id"),
            InventoryItem.project_id,
            InventoryItem.name,
            InventoryItem.unit,
            InventoryItem.quantity_on_hand,
            func.coalesce(func.sum(StockMovement.quantity * _ledger_sign()), 0).label("ledger_balance"),
        )
        .outerjoin(StockMovement, StockMovement.item_id == InventoryItem.id)
        .where(InventoryItem.project_id == project_id)
        .group_by(
            InventoryItem.id,
            InventoryItem.project_id,
            InventoryItem.name,
            InventoryItem.unit,
            InventoryItem.quantity_on_hand,
        )
        .order_by(InventoryItem.name)
    )
    rows = (await db.execute(stmt)).mappings().all()

    return [
        {
            "item_id": row["item_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "unit": row["unit"],
            "quantity_on_hand": Decimal(row["quantity_on_hand"]),
            "ledger_balance": Decimal(row["ledger_balance"]),
            "matches": Decimal(row["quantity_on_hand"]) == Decimal(row["ledger_balance"]),
        }
        for row in rows
    ]