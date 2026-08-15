"""Procurement tool for the ICE Copilot (AI-1): get_purchase_orders."""
from __future__ import annotations

import uuid
from typing import Any

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.ai.context import ActorContext
from app.ai.tools.base import (
    actor_from,
    bound_items,
    current_db,
    get_project_any,
    require_role,
    safe_tool,
)
from app.models.purchase_order import POStatus, PurchaseOrder
from app.models.user import UserRole
from app.models.vendor import Vendor


@tool
@safe_tool
async def get_purchase_orders(
    project_id: uuid.UUID,
    status: POStatus | None = None,
    limit: int = 20,
    runtime: ToolRuntime[ActorContext] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """List purchase orders for a project with status, vendor, total amount and
    line counts, optionally filtered by status. Use for 'open purchase orders',
    'what's on order'. Admin and procurement only."""
    actor = actor_from(runtime)
    require_role(actor, UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)
    db = current_db()
    project = await get_project_any(db, project_id)

    stmt = (
        select(PurchaseOrder, Vendor.name)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(PurchaseOrder.project_id == project.id)
        .options(selectinload(PurchaseOrder.lines))
        .order_by(PurchaseOrder.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == status)
    result = await db.execute(stmt)
    rows: list[dict[str, Any]] = []
    for po, vendor_name in result.all():
        rows.append(
            {
                "po_id": str(po.id),
                "po_number": po.po_number,
                "vendor_name": vendor_name,
                "status": po.status.value,
                "total_amount": float(po.total_amount),
                "order_date": po.order_date.isoformat() if po.order_date else None,
                "expected_delivery": (
                    po.expected_delivery.isoformat() if po.expected_delivery else None
                ),
                "line_count": len(po.lines),
            }
        )
    return bound_items(rows, total_count=len(rows), limit=limit)
