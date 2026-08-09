"""
Basic inventory endpoints — items tracked per project, with an immutable
stock-movement ledger. quantity_on_hand on InventoryItem is a denormalized
running total updated every time a movement is recorded; the ledger itself
(stock_movements) is the audit-grade source of truth.

Write access: Admin and Procurement Manager (matches the "procurement
manages inventory" role split from the Phase 1 design). Read access follows
the same project-visibility rule as everything else.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.api.project_access import assert_can_view_project, get_project_or_404
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.inventory import InventoryItem, MovementType, StockMovement
from app.models.user import User, UserRole
from app.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
    StockMovementCreate,
    StockMovementRead,
)

router = APIRouter(prefix="/projects/{project_id}/inventory", tags=["inventory"])

write_roles = require_role(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)

# Sign convention applied to every movement — see MovementType docstring.
_MOVEMENT_SIGN = {
    MovementType.RECEIVED: 1,
    MovementType.ADJUSTED: 1,
    MovementType.CONSUMED: -1,
    MovementType.TRANSFERRED: -1,
}


@router.get("", response_model=list[InventoryItemRead])
async def list_inventory_items(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_or_404(db, project_id)
    await assert_can_view_project(db, user, project)

    result = await db.execute(
        select(InventoryItem).where(InventoryItem.project_id == project_id).order_by(InventoryItem.name)
    )
    return result.scalars().all()


@router.post("", response_model=InventoryItemRead, status_code=status.HTTP_201_CREATED)
async def create_inventory_item(
    project_id: uuid.UUID,
    payload: InventoryItemCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    await get_project_or_404(db, project_id)

    data = payload.model_dump(exclude={"opening_quantity"})
    item = InventoryItem(project_id=project_id, quantity_on_hand=0, **data)
    db.add(item)
    await db.flush()

    if payload.opening_quantity > 0:
        db.add(
            StockMovement(
                item_id=item.id,
                recorded_by=user.id,
                movement_type=MovementType.RECEIVED,
                quantity=payload.opening_quantity,
                note="Opening balance",
            )
        )
        item.quantity_on_hand = payload.opening_quantity

    await record_audit(
        db,
        user_id=user.id,
        action="create",
        table_name="inventory_items",
        record_id=str(item.id),
        changes={"name": {"old": None, "new": item.name}},
    )

    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=InventoryItemRead)
async def update_inventory_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: InventoryItemUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    item = await _get_item_or_404(db, project_id, item_id)

    changes = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        old_value = getattr(item, field, None)
        if old_value != value:
            changes[field] = {"old": old_value, "new": value}
        setattr(item, field, value)

    await db.flush()

    if changes:
        await record_audit(
            db,
            user_id=user.id,
            action="update",
            table_name="inventory_items",
            record_id=str(item.id),
            changes=changes,
        )

    await db.commit()
    await db.refresh(item)
    return item


@router.post(
    "/{item_id}/movements", response_model=StockMovementRead, status_code=status.HTTP_201_CREATED
)
async def record_movement(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: StockMovementCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    item = await _get_item_or_404(db, project_id, item_id)

    signed_quantity = payload.quantity * _MOVEMENT_SIGN[payload.movement_type]
    new_balance = float(item.quantity_on_hand) + signed_quantity
    if new_balance < 0:
        raise HTTPException(
            status_code=400,
            detail=f"Movement would take {item.name} below zero (have {item.quantity_on_hand} {item.unit})",
        )

    movement = StockMovement(
        item_id=item.id,
        recorded_by=user.id,
        movement_type=payload.movement_type,
        quantity=payload.quantity,
        note=payload.note,
    )
    db.add(movement)
    item.quantity_on_hand = new_balance
    await db.flush()

    await record_audit(
        db,
        user_id=user.id,
        action="create",
        table_name="stock_movements",
        record_id=str(movement.id),
        changes={
            "quantity_on_hand": {"old": float(item.quantity_on_hand) - signed_quantity, "new": new_balance}
        },
    )

    await db.commit()
    await db.refresh(movement)
    return movement


@router.get("/{item_id}/movements", response_model=list[StockMovementRead])
async def list_movements(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_or_404(db, project_id)
    await assert_can_view_project(db, user, project)
    await _get_item_or_404(db, project_id, item_id)

    result = await db.execute(
        select(StockMovement).where(StockMovement.item_id == item_id).order_by(StockMovement.created_at.desc())
    )
    return result.scalars().all()


async def _get_item_or_404(db: AsyncSession, project_id: uuid.UUID, item_id: uuid.UUID) -> InventoryItem:
    await get_project_or_404(db, project_id)
    result = await db.execute(
        select(InventoryItem).where(InventoryItem.id == item_id, InventoryItem.project_id == project_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return item
