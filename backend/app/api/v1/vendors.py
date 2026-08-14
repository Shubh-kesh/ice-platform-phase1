"""
Vendor master-data endpoints (Phase 5, M14).

Global (not project-scoped) — vendors are enterprise master data shared across
all projects, so these routes use only role gates (no assert_can_view_project:
there is no project to check). RBAC per the M14 plan: admin + procurement only;
supervisors/clients get 403 and never see vendor rows.

Soft deactivation only: PATCH with is_active=false blocks *future* PO creation
but never hides or invalidates existing POs. POST is idempotency-protected
(M8); duplicate vendor names return 409 (app-level check + uq_vendors_name as
the DB backstop for concurrent no-key requests).
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_idempotency_guard, require_role
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.user import User, UserRole
from app.models.vendor import Vendor
from app.schemas.vendor import VendorCreate, VendorRead, VendorUpdate
from app.services.idempotency import IdempotencyGuard

router = APIRouter(prefix="/vendors", tags=["vendors"])

admin_proc = require_role(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)


@router.get("", response_model=list[VendorRead])
async def list_vendors(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(admin_proc)],
):
    """All vendors (active + deactivated), ordered by name. is_active is part of
    the shape so the UI can show the soft-deactivate toggle."""
    result = await db.execute(select(Vendor).order_by(Vendor.name.asc()))
    return result.scalars().all()


@router.post("", response_model=VendorRead, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    payload: VendorCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
    idem: Annotated[IdempotencyGuard, Depends(get_idempotency_guard)],
):
    """Create a vendor. Name is unique — a duplicate returns 409. Idempotency-
    protected: a retry replays the stored vendor instead of creating a second
    row; a failed attempt frees the key for a safe retry."""
    if idem.replay is not None:
        return idem.replay

    existing = await db.execute(select(Vendor).where(Vendor.name == payload.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409, detail="A vendor with this name already exists"
        )

    vendor = Vendor(
        name=payload.name,
        contact_name=payload.contact_name,
        email=payload.email,
        phone=payload.phone,
        payment_terms=payload.payment_terms,
        address=payload.address,
        notes=payload.notes,
        is_active=True,
    )
    db.add(vendor)
    try:
        await db.flush()
    except IntegrityError:
        # uq_vendors_name backstop for two concurrent no-key creates that both
        # passed the app-level check before either committed.
        raise HTTPException(
            status_code=409, detail="A vendor with this name already exists"
        ) from None

    await record_audit(
        db,
        user_id=user.id,
        action="vendor_create",
        table_name="vendors",
        record_id=str(vendor.id),
        changes={
            "name": {"old": None, "new": vendor.name},
            "contact_name": {"old": None, "new": vendor.contact_name},
            "email": {"old": None, "new": vendor.email},
            "phone": {"old": None, "new": vendor.phone},
            "payment_terms": {"old": None, "new": vendor.payment_terms},
            "is_active": {"old": None, "new": True},
        },
    )

    await idem.finish(
        db, status_code=status.HTTP_201_CREATED, response_model=VendorRead, obj=vendor
    )
    await db.commit()
    await db.refresh(vendor)
    return vendor


@router.get("/{vendor_id}", response_model=VendorRead)
async def get_vendor(
    vendor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(admin_proc)],
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendor


@router.patch("/{vendor_id}", response_model=VendorRead)
async def update_vendor(
    vendor_id: uuid.UUID,
    payload: VendorUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")

    if payload.name is not None and payload.name != vendor.name:
        existing = await db.execute(
            select(Vendor.id).where(
                Vendor.name == payload.name,
                Vendor.id != vendor.id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409, detail="A vendor with this name already exists"
            )

    changes: dict = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        old = getattr(vendor, field)
        if old != value:
            changes[field] = {"old": old, "new": value}
        setattr(vendor, field, value)

    try:
        await db.flush()
    except IntegrityError:
        # uq_vendors_name backstop for a concurrent rename race that both passed
        # the app-level check above before either committed (409, never a 500).
        raise HTTPException(
            status_code=409, detail="A vendor with this name already exists"
        ) from None

    if changes:
        await record_audit(
            db,
            user_id=user.id,
            action="vendor_update",
            table_name="vendors",
            record_id=str(vendor.id),
            changes=changes,
        )
    await db.commit()
    await db.refresh(vendor)
    return vendor
