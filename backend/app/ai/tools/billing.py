"""Billing tools (W7.3): get_billing_milestones, get_invoices."""
from __future__ import annotations

import uuid
from typing import Any

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from app.ai.context import ActorContext
from app.ai.tools.base import (
    actor_from,
    bound_items,
    current_db,
    get_project_any,
    get_project_visible,
    load_user,
    require_role,
    safe_tool,
)
from app.models.finance import BillingMilestone, Invoice, InvoiceStatus
from app.models.user import UserRole


@tool
@safe_tool
async def get_billing_milestones(
    project_id: uuid.UUID, limit: int = 50, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """List billing milestones (schedule of values) for a project: name, billing
    rule, status. Admin and procurement only."""
    actor = actor_from(runtime)
    require_role(actor, UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)
    db = current_db()
    project = await get_project_any(db, project_id)

    result = await db.execute(
        select(BillingMilestone)
        .where(BillingMilestone.project_id == project.id)
        .order_by(BillingMilestone.sort_order)
    )
    milestones = list(result.scalars().all())
    rows = [
        {
            "milestone_id": str(m.id),
            "name": m.name,
            "billing_type": m.billing_type.value,
            "billing_percentage": float(m.billing_percentage)
            if m.billing_percentage is not None
            else None,
            "fixed_amount": float(m.fixed_amount) if m.fixed_amount is not None else None,
            "status": m.status.value,
        }
        for m in milestones
    ]
    return bound_items(rows, total_count=len(rows), limit=limit)


@tool
@safe_tool
async def get_invoices(
    project_id: uuid.UUID, limit: int = 50, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """List invoices/payment requests for a project. Admin/procurement see the
    full set; clients see only ISSUED (sent/paid/cancelled) requests in a
    restricted shape — never drafts, never internal billing rules."""
    actor = actor_from(runtime)
    db = current_db()
    if actor.role == UserRole.CLIENT:
        user = await load_user(db, actor)
        project = await get_project_visible(db, user, project_id)
        stmt = (
            select(Invoice)
            .where(Invoice.project_id == project.id, Invoice.status != InvoiceStatus.DRAFT)
            .order_by(Invoice.created_at.desc())
        )
        result = await db.execute(stmt)
        invoices = list(result.scalars().all())
        rows = [
            {
                "invoice_id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "milestone_name": inv.milestone_name,
                "amount": float(inv.amount),
                "status": inv.status.value,
                "due_date": inv.due_date.isoformat(),
            }
            for inv in invoices
        ]
        return bound_items(rows, total_count=len(rows), limit=limit)

    require_role(actor, UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)
    project = await get_project_any(db, project_id)
    result = await db.execute(
        select(Invoice).where(Invoice.project_id == project.id).order_by(Invoice.created_at.desc())
    )
    invoices = list(result.scalars().all())
    rows = [
        {
            "invoice_id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "milestone_name": inv.milestone_name,
            "amount": float(inv.amount),
            "status": inv.status.value,
            "due_date": inv.due_date.isoformat(),
            "created_at": inv.created_at.isoformat(),
        }
        for inv in invoices
    ]
    return bound_items(rows, total_count=len(rows), limit=limit)
