"""Inventory tool for the ICE Copilot (AI-1): get_project_inventory."""
from __future__ import annotations

import uuid
from typing import Any

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from app.ai.context import ActorContext
from app.ai.tools.base import (
    actor_from,
    assert_not_client_role,
    bound_items,
    current_db,
    get_project_visible,
    load_user,
    safe_tool,
)
from app.models.inventory import InventoryItem


@tool
@safe_tool
async def get_project_inventory(
    project_id: uuid.UUID, limit: int = 50, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """List inventory items for a project with on-hand quantity, unit,
    low-stock flag and (where the caller may see it) unit cost. Use for
    'show inventory', 'how much cement do we have', low-stock questions."""
    actor = actor_from(runtime)
    db = current_db()
    user = await load_user(db, actor)
    # M6: inventory/procurement data is off-limits to clients; supervisors keep
    # the REST-equivalent assigned-project read (assert_can_view_project below).
    assert_not_client_role(actor)
    project = await get_project_visible(db, user, project_id)

    result = await db.execute(
        select(InventoryItem)
        .where(InventoryItem.project_id == project.id)
        .order_by(InventoryItem.name)
    )
    items = list(result.scalars().all())
    rows = [
        {
            "item_id": str(item.id),
            "name": item.name,
            "unit": item.unit,
            "quantity_on_hand": float(item.quantity_on_hand),
            "reorder_threshold": (
                float(item.reorder_threshold) if item.reorder_threshold is not None else None
            ),
            "low_stock": (
                item.reorder_threshold is not None
                and item.quantity_on_hand <= item.reorder_threshold
            ),
            "unit_cost": float(item.unit_cost) if item.unit_cost is not None else None,
        }
        for item in items
    ]
    return bound_items(rows, total_count=len(rows), limit=limit)


@tool
@safe_tool
async def get_project_inventory_movements(
    project_id: uuid.UUID, item_id: uuid.UUID, limit: int = 20, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """List the immutable stock-movement ledger for one inventory item (type,
    quantity, note, date). Use for stock history questions."""
    from sqlalchemy import select

    from app.models.inventory import StockMovement

    actor = actor_from(runtime)
    db = current_db()
    user = await load_user(db, actor)
    assert_not_client_role(actor)
    project = await get_project_visible(db, user, project_id)
    # IDOR: the item must belong to the project.
    item_result = await db.execute(
        select(InventoryItem).where(
            InventoryItem.id == item_id, InventoryItem.project_id == project.id
        )
    )
    item = item_result.scalar_one_or_none()
    if item is None:
        return {"error": "not_found", "detail": "Inventory item not found"}
    result = await db.execute(
        select(StockMovement)
        .where(StockMovement.item_id == item_id)
        .order_by(StockMovement.created_at.desc())
    )
    movements = list(result.scalars().all())
    rows = [
        {
            "movement_id": str(m.id),
            "movement_type": m.movement_type.value,
            "quantity": float(m.quantity),
            "note": m.note,
            "created_at": m.created_at.isoformat(),
        }
        for m in movements
    ]
    return bound_items(rows, total_count=len(rows), limit=limit)
