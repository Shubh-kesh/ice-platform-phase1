"""
Purchase-order endpoints (Phase 5, M14).

Project-scoped commitment documents: vendor + lines + derived totals + an
audited, role-gated lifecycle. M14 POs create no job costs and no stock
movements (delivery verification / receiving is M15).

RBAC (per the M14 plan §10):
  * admin + procurement: list/get/create/header-PATCH/line ops/submit/revise/
    resubmit, and cancel of DRAFT/PENDING_APPROVAL.
  * admin only: approve, reject, and cancel of APPROVED.
  * supervisors/clients: 403 on every route (no PO shape exists for them).

Lifecycle (no status PATCH — dedicated, row-locked, audited transitions):
    DRAFT -> submit (>=1 line) -> PENDING_APPROVAL -> approve -> APPROVED
    PENDING_APPROVAL -> reject (reason) -> REJECTED
    REJECTED -> revise -> DRAFT | resubmit -> PENDING_APPROVAL
    DRAFT|PENDING_APPROVAL -> cancel; APPROVED -> cancel (admin only)

Concurrency (plan §17): every mutation takes the project row lock FIRST
(get_project_for_update — serializes po_number allocation and total recompute),
then the PO row lock for transitions/edits (SELECT ... FOR UPDATE). The order
project -> PO is never reversed, so lock graphs are acyclic.

Idempotency (M8): POST (create PO + nested lines) and POST (add line) are
idempotency-protected; transitions are deliberately unprotected (state-machine
guarded). Totals are always server-derived and recomputed in-transaction.
"""
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_idempotency_guard, require_role
from app.api.project_access import (
    assert_project_writable,
    get_project_for_update,
    get_project_or_404,
)
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.project import Project, ProjectStatus
from app.models.purchase_order import POLine, POStatus, PurchaseOrder
from app.models.user import User, UserRole
from app.models.vendor import Vendor
from app.schemas.purchase_order import (
    POLineCreate,
    POLineRead,
    POLineUpdate,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    PurchaseOrderReject,
    PurchaseOrderUpdate,
)
from app.services.idempotency import IdempotencyGuard
from app.services.notifications import (
    notify_po_approved,
    notify_po_rejected,
    notify_po_submitted,
)
from app.services.purchase_orders import (
    line_total,
    next_po_seq,
    po_number_for,
    refresh_po_total,
    tax_amount,
)

router = APIRouter(prefix="/projects/{project_id}/purchase-orders", tags=["purchase_orders"])

admin_only = require_role(UserRole.ADMIN)
admin_proc = require_role(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _assert_po_writable(project: Project) -> None:
    """POs are a commitment that can be raised during planning, so
    DRAFT/PLANNING/ON_HOLD/ACTIVE projects are writable. COMPLETED freezes them
    (400); ARCHIVED is read-only via assert_project_writable (403)."""
    assert_project_writable(project)
    if project.status == ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=400, detail="Purchase orders are frozen on COMPLETED projects"
        )


async def _get_po_locked(
    db: AsyncSession, project_id: uuid.UUID, po_id: uuid.UUID
) -> PurchaseOrder:
    """Load a PO with a PostgreSQL row lock (SELECT ... FOR UPDATE), scoped to
    the project (cross-project id -> 404, the M5 IDOR doctrine)."""
    result = await db.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id, PurchaseOrder.project_id == project_id)
        .with_for_update()
    )
    po = result.scalar_one_or_none()
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po


async def _load_active_vendor(db: AsyncSession, vendor_id: uuid.UUID) -> Vendor:
    """A PO can only be created/pointed at an existing, active vendor."""
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    if not vendor.is_active:
        raise HTTPException(
            status_code=400,
            detail="This vendor is deactivated and cannot be used for new purchase orders",
        )
    return vendor


async def _load_po_read(
    db: AsyncSession, project_id: uuid.UUID, po_id: uuid.UUID
) -> tuple[PurchaseOrder, Vendor]:
    """Load a PO with its lines + vendor for read serialization (no lock)."""
    result = await db.execute(
        select(PurchaseOrder, Vendor)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(PurchaseOrder.id == po_id, PurchaseOrder.project_id == project_id)
        .options(selectinload(PurchaseOrder.lines))
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return row[0], row[1]


def _attach_line_totals(lines: list[POLine]) -> list[POLine]:
    """Derive each line's line_total (qty x price, ROUND_HALF_UP) — never
    stored, attached before serialization (the setattr doctrine)."""
    for line in lines:
        setattr(line, "line_total", float(line_total(line.quantity, line.unit_price)))
    return lines


def _serialize_po(po: PurchaseOrder, vendor: Vendor, project: Project) -> PurchaseOrder:
    """Attach the transient read fields: project_code, vendor_name, and the
    derived subtotal/tax_amount. total_amount is the stored denormalized value."""
    _attach_line_totals(po.lines)
    subtotal = sum(
        (line_total(line.quantity, line.unit_price) for line in po.lines),
        Decimal("0"),
    )
    setattr(po, "project_code", project.project_code)
    setattr(po, "vendor_name", vendor.name)
    setattr(po, "subtotal", float(subtotal))
    setattr(po, "tax_amount", float(tax_amount(subtotal, po.tax_rate)))
    return po


async def _lines_for(db: AsyncSession, po_id: uuid.UUID) -> list[POLine]:
    result = await db.execute(
        select(POLine).where(POLine.purchase_order_id == po_id)
    )
    return list(result.scalars().all())


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _finish_idempotency_po_create(
    db: AsyncSession,
    idem: IdempotencyGuard,
    *,
    po: PurchaseOrder,
    vendor: Vendor,
    project: Project,
) -> None:
    """Finalize the PO-create Idempotency-Key claim with a relationship-safe body.

    IdempotencyGuard.finish() refreshes the object before serializing, and that
    refresh expires loaded ORM relationships — in async that makes
    model_validate() lazy-load and raise MissingGreenlet. The PO read shape
    includes the `lines` relationship, so this mirrors finish() locally (public
    IdempotencyRecord columns only — if M8 ever grows more record columns, keep
    this in lockstep with IdempotencyGuard.finish) and re-attaches the lines
    after the server-default refresh. M8's service is left untouched.
    """
    if not idem.enabled or idem.record is None:
        return
    await db.flush()
    # Refresh only the server-default columns. A full db.refresh(po) would expire
    # the loaded `lines` relationship, whose async re-load would raise; naming
    # the columns leaves the relationship intact, then each line's timestamps are
    # refreshed in place (their objects never expire).
    await db.refresh(po, ["created_at", "updated_at"])
    for line in po.lines:
        await db.refresh(line, ["created_at", "updated_at"])
    _serialize_po(po, vendor, project)
    body = PurchaseOrderRead.model_validate(po).model_dump(mode="json")
    idem.record.status = "completed"
    idem.record.response_status = status.HTTP_201_CREATED
    idem.record.response_body = json.dumps(body, sort_keys=True, separators=(",", ":"))
    idem.record.completed_at = _now()


# --- Read --------------------------------------------------------------------


@router.get("", response_model=list[PurchaseOrderRead])
async def list_purchase_orders(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(admin_proc)],
):
    """POs for a project, newest first. Admin/procurement only — supervisors and
    clients never see a PO shape (M4/M5 finance precedent)."""
    project = await get_project_or_404(db, project_id)
    result = await db.execute(
        select(PurchaseOrder, Vendor)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(PurchaseOrder.project_id == project_id)
        .options(selectinload(PurchaseOrder.lines))
        .order_by(PurchaseOrder.created_at.desc())
    )
    rows = result.all()
    return [_serialize_po(po, vendor, project) for po, vendor in rows]


@router.get("/{po_id}", response_model=PurchaseOrderRead)
async def get_purchase_order(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(admin_proc)],
):
    project = await get_project_or_404(db, project_id)
    po, vendor = await _load_po_read(db, project_id, po_id)
    return _serialize_po(po, vendor, project)


# --- Create / header PATCH ----------------------------------------------------


@router.post("", response_model=PurchaseOrderRead, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(
    project_id: uuid.UUID,
    payload: PurchaseOrderCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
    idem: Annotated[IdempotencyGuard, Depends(get_idempotency_guard)],
):
    """Create a PO (optionally with nested lines) and get its auto-generated
    po_number (PO-{project_code}-{seq:04d}) + server-derived total. The project
    row lock serializes po_number allocation. Idempotency-protected: a retry
    replays the stored PO instead of creating a second."""
    if idem.replay is not None:
        return idem.replay

    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    vendor = await _load_active_vendor(db, payload.vendor_id)

    seq = await next_po_seq(db, project.id)
    po = PurchaseOrder(
        po_number=po_number_for(project.project_code, seq),
        project_id=project.id,
        vendor_id=vendor.id,
        status=POStatus.DRAFT,
        order_date=payload.order_date or _today(),
        expected_delivery=payload.expected_delivery,
        tax_rate=(Decimal(str(payload.tax_rate)) if payload.tax_rate is not None else None),
        notes=payload.notes,
        total_amount=Decimal("0"),
        created_by=user.id,
    )
    po.lines = [
        POLine(
            description=line.description,
            quantity=Decimal(str(line.quantity)),
            unit=line.unit,
            unit_price=Decimal(str(line.unit_price)),
            cost_code=line.cost_code,
        )
        for line in payload.lines
    ]
    db.add(po)
    await db.flush()
    await refresh_po_total(db, po)

    await record_audit(
        db,
        user_id=user.id,
        action="purchase_order_create",
        table_name="purchase_orders",
        record_id=str(po.id),
        changes={
            "po_number": {"old": None, "new": po.po_number},
            "project_id": {"old": None, "new": str(po.project_id)},
            "vendor_id": {"old": None, "new": str(po.vendor_id)},
            "line_count": {"old": None, "new": len(po.lines)},
            "total_amount": {"old": None, "new": float(po.total_amount)},
            "status": {"old": None, "new": POStatus.DRAFT.value},
        },
    )

    _serialize_po(po, vendor, project)
    await _finish_idempotency_po_create(db, idem, po=po, vendor=vendor, project=project)
    await db.commit()
    po, vendor = await _load_po_read(db, project_id, po.id)
    return _serialize_po(po, vendor, project)


@router.patch("/{po_id}", response_model=PurchaseOrderRead)
async def update_purchase_order(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    payload: PurchaseOrderUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
):
    """DRAFT header fields only (vendor/order_date/expected_delivery/tax_rate/
    notes). status is never PATCH-able. If tax_rate changes, the total is
    recomputed in the same transaction."""
    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status != POStatus.DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Purchase order header can only be edited in DRAFT",
        )

    if payload.vendor_id is not None and payload.vendor_id != po.vendor_id:
        vendor = await _load_active_vendor(db, payload.vendor_id)
        changes: dict = {
            "vendor_id": {"old": str(po.vendor_id), "new": str(vendor.id)},
        }
        po.vendor_id = vendor.id
    else:
        changes = {}

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "vendor_id":
            continue  # handled above (locked inside the active-vendor check)
        new_value: object
        if field == "tax_rate":
            new_value = Decimal(str(value)) if value is not None else None
        else:
            new_value = value
        old = getattr(po, field)
        if old != new_value:
            changes[field] = {
                "old": float(old) if isinstance(old, Decimal) else old,
                "new": float(new_value) if isinstance(new_value, Decimal) else new_value,
            }
        setattr(po, field, new_value)

    await refresh_po_total(db, po)
    await db.flush()

    if changes:
        await record_audit(
            db,
            user_id=user.id,
            action="purchase_order_update",
            table_name="purchase_orders",
            record_id=str(po.id),
            changes=changes,
        )
    await db.commit()
    po, vendor = await _load_po_read(db, project_id, po.id)
    return _serialize_po(po, vendor, project)


# --- Lifecycle transitions ----------------------------------------------------


@router.post("/{po_id}/submit", response_model=PurchaseOrderRead)
async def submit_purchase_order(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
):
    """DRAFT -> PENDING_APPROVAL. Requires at least one line. Notifies all
    active admins that an approval task awaits (atomic with the transition)."""
    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status != POStatus.DRAFT:
        raise HTTPException(
            status_code=400, detail="Only DRAFT purchase orders can be submitted"
        )
    lines = await _lines_for(db, po.id)
    if not lines:
        raise HTTPException(
            status_code=400,
            detail="A purchase order needs at least one line before it can be submitted",
        )

    now = _now()
    po.status = POStatus.PENDING_APPROVAL
    po.submitted_at = now
    po.submitted_by = user.id
    await db.flush()

    await record_audit(
        db,
        user_id=user.id,
        action="po_submit",
        table_name="purchase_orders",
        record_id=str(po.id),
        changes={
            "status": {"old": POStatus.DRAFT.value, "new": POStatus.PENDING_APPROVAL.value},
            "submitted_at": {"old": None, "new": now.isoformat()},
            "submitted_by": {"old": None, "new": str(user.id)},
        },
    )
    await notify_po_submitted(db, project.id, po.po_number)
    await db.commit()
    po, vendor = await _load_po_read(db, project_id, po.id)
    return _serialize_po(po, vendor, project)


@router.post("/{po_id}/approve", response_model=PurchaseOrderRead)
async def approve_purchase_order(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """PENDING_APPROVAL -> APPROVED. Admin-only (the ROADMAP approve-step
    RBAC). APPROVED is terminal in M14."""
    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail="Only PENDING_APPROVAL purchase orders can be approved",
        )

    now = _now()
    po.status = POStatus.APPROVED
    po.approved_at = now
    po.approved_by = admin.id
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="po_approve",
        table_name="purchase_orders",
        record_id=str(po.id),
        changes={
            "status": {
                "old": POStatus.PENDING_APPROVAL.value,
                "new": POStatus.APPROVED.value,
            },
            "approved_at": {"old": None, "new": now.isoformat()},
            "approved_by": {"old": None, "new": str(admin.id)},
        },
    )
    await notify_po_approved(db, project.id, po.po_number, po.created_by)
    await db.commit()
    po, vendor = await _load_po_read(db, project_id, po.id)
    return _serialize_po(po, vendor, project)


@router.post("/{po_id}/reject", response_model=PurchaseOrderRead)
async def reject_purchase_order(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    payload: PurchaseOrderReject,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """PENDING_APPROVAL -> REJECTED. Admin-only; a rejection reason is required
    (schema-level, 422 if missing/empty). Notifies the PO creator + admins."""
    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status != POStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail="Only PENDING_APPROVAL purchase orders can be rejected",
        )

    now = _now()
    po.status = POStatus.REJECTED
    po.rejected_at = now
    po.rejected_by = admin.id
    po.rejected_reason = payload.rejected_reason
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="po_reject",
        table_name="purchase_orders",
        record_id=str(po.id),
        changes={
            "status": {
                "old": POStatus.PENDING_APPROVAL.value,
                "new": POStatus.REJECTED.value,
            },
            "rejected_at": {"old": None, "new": now.isoformat()},
            "rejected_by": {"old": None, "new": str(admin.id)},
            "rejected_reason": {"old": None, "new": payload.rejected_reason},
        },
    )
    await notify_po_rejected(db, project.id, po.po_number, po.created_by)
    await db.commit()
    po, vendor = await _load_po_read(db, project_id, po.id)
    return _serialize_po(po, vendor, project)


@router.post("/{po_id}/revise", response_model=PurchaseOrderRead)
async def revise_purchase_order(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
):
    """REJECTED -> DRAFT: the creator edits the PO again. Rejection history
    (reason/at/by) is retained on the row; the audit log is the full trail."""
    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status != POStatus.REJECTED:
        raise HTTPException(
            status_code=400, detail="Only REJECTED purchase orders can be revised"
        )

    po.status = POStatus.DRAFT
    await db.flush()

    await record_audit(
        db,
        user_id=user.id,
        action="po_revise",
        table_name="purchase_orders",
        record_id=str(po.id),
        changes={
            "status": {"old": POStatus.REJECTED.value, "new": POStatus.DRAFT.value},
        },
    )
    await db.commit()
    po, vendor = await _load_po_read(db, project_id, po.id)
    return _serialize_po(po, vendor, project)


@router.post("/{po_id}/resubmit", response_model=PurchaseOrderRead)
async def resubmit_purchase_order(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
):
    """REJECTED -> PENDING_APPROVAL: resubmit without editing. Requires at
    least one line. A distinct, audited transition that fires a fresh
    po_submitted notification."""
    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status != POStatus.REJECTED:
        raise HTTPException(
            status_code=400, detail="Only REJECTED purchase orders can be resubmitted"
        )
    lines = await _lines_for(db, po.id)
    if not lines:
        raise HTTPException(
            status_code=400,
            detail="A purchase order needs at least one line before it can be resubmitted",
        )

    now = _now()
    po.status = POStatus.PENDING_APPROVAL
    po.submitted_at = now
    po.submitted_by = user.id
    await db.flush()

    await record_audit(
        db,
        user_id=user.id,
        action="po_resubmit",
        table_name="purchase_orders",
        record_id=str(po.id),
        changes={
            "status": {
                "old": POStatus.REJECTED.value,
                "new": POStatus.PENDING_APPROVAL.value,
            },
            "submitted_at": {"old": None, "new": now.isoformat()},
            "submitted_by": {"old": None, "new": str(user.id)},
        },
    )
    await notify_po_submitted(db, project.id, po.po_number)
    await db.commit()
    po, vendor = await _load_po_read(db, project_id, po.id)
    return _serialize_po(po, vendor, project)


@router.post("/{po_id}/cancel", response_model=PurchaseOrderRead)
async def cancel_purchase_order(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
):
    """Cancel a PO. DRAFT/PENDING_APPROVAL: admin + procurement. APPROVED:
    admin only (403 otherwise). CANCELLED is terminal in M14."""
    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status == POStatus.APPROVED:
        if user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=403,
                detail="Only admins can cancel an approved purchase order",
            )
    elif po.status not in (POStatus.DRAFT, POStatus.PENDING_APPROVAL):
        raise HTTPException(
            status_code=400,
            detail="Only DRAFT, PENDING_APPROVAL or APPROVED purchase orders can be cancelled",
        )

    now = _now()
    old_status = po.status
    po.status = POStatus.CANCELLED
    po.cancelled_at = now
    po.cancelled_by = user.id
    await db.flush()

    await record_audit(
        db,
        user_id=user.id,
        action="po_cancel",
        table_name="purchase_orders",
        record_id=str(po.id),
        changes={
            "status": {"old": old_status.value, "new": POStatus.CANCELLED.value},
            "cancelled_at": {"old": None, "new": now.isoformat()},
            "cancelled_by": {"old": None, "new": str(user.id)},
        },
    )
    await db.commit()
    po, vendor = await _load_po_read(db, project_id, po.id)
    return _serialize_po(po, vendor, project)


# --- Line operations -----------------------------------------------------------


@router.post("/{po_id}/lines", response_model=POLineRead, status_code=status.HTTP_201_CREATED)
async def add_po_line(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    payload: POLineCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
    idem: Annotated[IdempotencyGuard, Depends(get_idempotency_guard)],
):
    """Add a line to a DRAFT PO and recompute the total. Idempotency-protected:
    a retry replays the stored line without re-adding or re-totalling."""
    if idem.replay is not None:
        return idem.replay

    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status != POStatus.DRAFT:
        raise HTTPException(
            status_code=400, detail="Lines can only be edited on DRAFT purchase orders"
        )

    old_total = po.total_amount
    line = POLine(
        purchase_order_id=po.id,
        description=payload.description,
        quantity=Decimal(str(payload.quantity)),
        unit=payload.unit,
        unit_price=Decimal(str(payload.unit_price)),
        cost_code=payload.cost_code,
    )
    db.add(line)
    await db.flush()
    await refresh_po_total(db, po)

    await record_audit(
        db,
        user_id=user.id,
        action="po_line_add",
        table_name="po_lines",
        record_id=str(line.id),
        changes={
            "purchase_order_id": {"old": None, "new": str(po.id)},
            "description": {"old": None, "new": line.description},
            "quantity": {"old": None, "new": float(line.quantity)},
            "unit": {"old": None, "new": line.unit},
            "unit_price": {"old": None, "new": float(line.unit_price)},
            "cost_code": {"old": None, "new": line.cost_code.value},
            "total_old": {"old": None, "new": float(old_total)},
            "total_new": {"old": None, "new": float(po.total_amount)},
        },
    )
    # line_total is derived on read — attach it before idem.finish so the stored
    # replay response carries the same shape a normal response would.
    setattr(line, "line_total", float(line_total(line.quantity, line.unit_price)))
    await idem.finish(db, status_code=status.HTTP_201_CREATED, response_model=POLineRead, obj=line)
    await db.commit()
    await db.refresh(line)
    setattr(line, "line_total", float(line_total(line.quantity, line.unit_price)))
    return line


@router.patch("/{po_id}/lines/{line_id}", response_model=POLineRead)
async def update_po_line(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: POLineUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
):
    """Edit a line on a DRAFT PO and recompute the total in the same txn."""
    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status != POStatus.DRAFT:
        raise HTTPException(
            status_code=400, detail="Lines can only be edited on DRAFT purchase orders"
        )

    result = await db.execute(
        select(POLine).where(
            POLine.id == line_id, POLine.purchase_order_id == po.id
        )
    )
    line = result.scalar_one_or_none()
    if line is None:
        raise HTTPException(status_code=404, detail="PO line not found")

    old_total = po.total_amount
    changes: dict = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in ("quantity", "unit_price"):
            new_value = Decimal(str(value)) if value is not None else None
        else:
            new_value = value
        old = getattr(line, field)
        if old != new_value:
            changes[field] = {
                "old": float(old) if isinstance(old, Decimal) else old,
                "new": float(new_value) if isinstance(new_value, Decimal) else new_value,
            }
        setattr(line, field, new_value)

    await refresh_po_total(db, po)
    await db.flush()

    changes["total_old"] = {"old": None, "new": float(old_total)}
    changes["total_new"] = {"old": None, "new": float(po.total_amount)}
    await record_audit(
        db,
        user_id=user.id,
        action="po_line_update",
        table_name="po_lines",
        record_id=str(line.id),
        changes=changes,
    )
    await db.commit()
    await db.refresh(line)
    setattr(line, "line_total", float(line_total(line.quantity, line.unit_price)))
    return line


@router.delete("/{po_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_po_line(
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    line_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(admin_proc)],
):
    """Remove a line from a DRAFT PO and recompute the total. 204. Line deletes
    are legitimate DRAFT edits (no hard deletes anywhere else)."""
    project = await get_project_for_update(db, project_id)
    _assert_po_writable(project)
    po = await _get_po_locked(db, project_id, po_id)

    if po.status != POStatus.DRAFT:
        raise HTTPException(
            status_code=400, detail="Lines can only be edited on DRAFT purchase orders"
        )

    result = await db.execute(
        select(POLine).where(
            POLine.id == line_id, POLine.purchase_order_id == po.id
        )
    )
    line = result.scalar_one_or_none()
    if line is None:
        raise HTTPException(status_code=404, detail="PO line not found")

    old_total = po.total_amount
    description = line.description
    await db.delete(line)
    await refresh_po_total(db, po)
    await db.flush()

    await record_audit(
        db,
        user_id=user.id,
        action="po_line_remove",
        table_name="po_lines",
        record_id=str(line_id),
        changes={
            "purchase_order_id": {"old": None, "new": str(po.id)},
            "description": {"old": None, "new": description},
            "total_old": {"old": None, "new": float(old_total)},
            "total_new": {"old": None, "new": float(po.total_amount)},
        },
    )
    await db.commit()
    return None
