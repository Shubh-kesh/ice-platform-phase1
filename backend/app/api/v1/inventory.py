"""
Basic inventory endpoints — items tracked per project, with an immutable
stock-movement ledger. quantity_on_hand on InventoryItem is a denormalized
running total updated every time a movement is recorded; the ledger itself
(stock_movements) is the audit-grade source of truth.

Movement writes take a PostgreSQL row lock (SELECT ... FOR UPDATE) so two
concurrent movements on the same item can never both decide against the same
starting balance — one of the Phase 1 critical integrity risks. A
reconciliation endpoint recomputes on-hand from the ledger to detect any
legacy drift.

Write access: Admin and Procurement Manager (matches the "procurement
manages inventory" role split from the Phase 1 design). Read access follows
the same project-visibility rule as everything else.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_idempotency_guard, require_role
from app.api.project_access import assert_project_writable, assert_can_view_project, get_project_or_404
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.inventory import InventoryItem, MovementType, StockMovement
from app.models.user import User, UserRole
from app.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemRead,
    InventoryItemUpdate,
    InventoryReconciliationRead,
    StockMovementCreate,
    StockMovementRead,
)
from app.services.idempotency import IdempotencyGuard
from app.services.inventory import MOVEMENT_SIGN, reconcile_project_inventory

router = APIRouter(prefix="/projects/{project_id}/inventory", tags=["inventory"])

write_roles = require_role(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)


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
    project = await get_project_or_404(db, project_id)
    assert_project_writable(project)  # ARCHIVED projects are read-only

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
    project = await get_project_or_404(db, project_id)
    assert_project_writable(project)  # ARCHIVED projects are read-only

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
    idem: Annotated[IdempotencyGuard, Depends(get_idempotency_guard)],
):
    """Record a stock movement on the immutable ledger.

    Protected by an Idempotency-Key: the ledger is append-only and
    quantity_on_hand is a running total, so a double-submitted movement would
    silently corrupt the balance — a retry must replay instead of re-execute.
    """
    if idem.replay is not None:
        return idem.replay

    item = await _get_item_or_404(db, project_id, item_id, for_update=True)
    project = await get_project_or_404(db, project_id)
    assert_project_writable(project)  # ARCHIVED projects are read-only

    signed_quantity = payload.quantity * MOVEMENT_SIGN[payload.movement_type]
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

    await idem.finish(
        db, status_code=status.HTTP_201_CREATED, response_model=StockMovementRead, obj=movement
    )
    await db.commit()
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


@router.get("/reconciliation", response_model=list[InventoryReconciliationRead])
async def reconcile_inventory(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER))],
):
    """
    Ledger-reconciliation report: every item's stored quantity_on_hand compared
    against the balance recomputed from the immutable stock_movements ledger.
    matches=false flags an item whose running total has drifted from the ledger
    (e.g. a legacy lost-update race) and needs an ADJUSTED correction movement.
    """
    await get_project_or_404(db, project_id)
    return await reconcile_project_inventory(db, project_id)


async def _get_item_or_404(
    db: AsyncSession, project_id: uuid.UUID, item_id: uuid.UUID, for_update: bool = False
) -> InventoryItem:
    await get_project_or_404(db, project_id)
    stmt = select(InventoryItem).where(InventoryItem.id == item_id, InventoryItem.project_id == project_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return item
