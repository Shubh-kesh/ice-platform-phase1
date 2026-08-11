"""
Invoicing endpoints — billing milestones + milestone-driven invoices (Phase 3, M5).

The billing/revenue surface, deliberately independent of the job-cost ledger
(expenditure). An admin creates billing milestones (schedule of values),
completes them as work is finished, and generates an invoice whose amount is
derived server-side from the milestone rule x Project.budget_total.

RBAC (owner decisions, Aug 11):
  - ADMIN owns everything (milestone config + invoice creation/transitions).
  - PROCUREMENT_MANAGER is view-only across the invoicing domain.
  - SITE_SUPERVISOR sees no finance surface (M4 precedent).
  - CLIENT sees only their assigned projects' invoices, in the restricted
    InvoiceClientRead shape (never budget/job-cost/external/notes fields).

Lifecycle:
  - Milestone config is editable until a project is COMPLETED (then frozen).
  - Invoice creation/transitions require an ACTIVE project.
  - ARCHIVED is read-only everywhere (assert_project_writable -> 403).
  - COMPLETED/ARCHIVED projects are immutable financial records — no hard
    delete path exists.

Concurrency: invoice creation holds the project row lock (M1/M4/M10 pattern)
so numbering is serialized; the partial unique index on
(billing_milestone_id) WHERE status <> 'CANCELLED' is the DB double-billing
guard. Invoice status transitions lock the invoice row (FOR UPDATE) so a
concurrent mark-paid/cancel can't both pass the same state guard.

Idempotency: POST /invoices reuses the M8 Idempotency-Key infrastructure — a
retry replays the stored response instead of generating a second invoice.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_idempotency_guard, require_role
from app.api.project_access import (
    assert_can_view_project,
    assert_project_writable,
    get_project_for_update,
    get_project_or_404,
)
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.finance import (
    BillingMilestone,
    BillingMilestoneStatus,
    BillingType,
    Invoice,
    InvoiceStatus,
)
from app.models.project import Project, ProjectStatus
from app.models.user import User, UserRole
from app.schemas.invoice import (
    BillingMilestoneCreate,
    BillingMilestoneRead,
    BillingMilestoneUpdate,
    InvoiceClientRead,
    InvoiceCreate,
    InvoiceRead,
)
from app.services.idempotency import IdempotencyGuard
from app.services.invoicing import (
    default_due_date,
    derive_overdue,
    invoice_number_for,
    milestone_amount,
    next_invoice_seq,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["invoicing"])

admin_only = require_role(UserRole.ADMIN)
admin_proc = require_role(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)

_FINANCE_READ_ROLES = (UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)


def _assert_milestones_writable(project: Project) -> None:
    """Milestone config is editable until a project is frozen (COMPLETED) or
    archived (ARCHIVED -> assert_project_writable -> 403)."""
    assert_project_writable(project)
    if project.status == ProjectStatus.COMPLETED:
        raise HTTPException(
            status_code=400, detail="Billing milestones are frozen on COMPLETED projects"
        )


def _assert_invoicing_active(project: Project) -> None:
    """Invoice creation and status transitions require an ACTIVE project."""
    assert_project_writable(project)  # ARCHIVED -> 403
    if project.status != ProjectStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail="Invoices can only be created or changed on ACTIVE projects",
        )


async def _get_milestone_or_404(
    db: AsyncSession, project_id: uuid.UUID, milestone_id: uuid.UUID
) -> BillingMilestone:
    result = await db.execute(
        select(BillingMilestone)
        .where(BillingMilestone.id == milestone_id, BillingMilestone.project_id == project_id)
        .with_for_update()
    )
    milestone = result.scalar_one_or_none()
    if milestone is None:
        raise HTTPException(status_code=404, detail="Billing milestone not found")
    return milestone


async def _get_invoice_locked(
    db: AsyncSession, project_id: uuid.UUID, invoice_id: uuid.UUID
) -> Invoice:
    """Load an invoice with a PostgreSQL row lock (SELECT ... FOR UPDATE) so
    concurrent status transitions serialize instead of both passing the same
    state guard (the M1/M4/M10 row-lock doctrine)."""
    result = await db.execute(
        select(Invoice)
        .where(Invoice.id == invoice_id, Invoice.project_id == project_id)
        .with_for_update()
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _attach_read_fields(invoice: Invoice, project: Project) -> Invoice:
    """Transient (non-mapped) fields consumed by the read schemas. setattr is
    deliberate: these are not mapped columns (the codebase setattr doctrine,
    cf. inventory/projects/users PATCH handlers)."""
    setattr(invoice, "project_code", project.project_code)
    setattr(invoice, "overdue", derive_overdue(invoice.status, invoice.due_date, _today()))
    return invoice


# --- Billing milestones ----------------------------------------------------


@router.get("/billing-milestones", response_model=list[BillingMilestoneRead])
async def list_billing_milestones(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(admin_proc)],
):
    """Schedule-of-values for a project. Admin/procurement read (procurement is
    view-only — clients/supervisors never see the billing configuration)."""
    await get_project_or_404(db, project_id)
    result = await db.execute(
        select(BillingMilestone)
        .where(BillingMilestone.project_id == project_id)
        .order_by(BillingMilestone.sort_order.asc(), BillingMilestone.created_at.asc())
    )
    return result.scalars().all()


@router.post(
    "/billing-milestones",
    response_model=BillingMilestoneRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_billing_milestone(
    project_id: uuid.UUID,
    payload: BillingMilestoneCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    project = await get_project_or_404(db, project_id)
    _assert_milestones_writable(project)

    existing = await db.execute(
        select(BillingMilestone.id).where(
            BillingMilestone.project_id == project_id,
            BillingMilestone.name == payload.name,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="A billing milestone with this name already exists",
        )

    milestone = BillingMilestone(
        project_id=project_id,
        name=payload.name,
        billing_type=payload.billing_type,
        billing_percentage=(
            Decimal(str(payload.billing_percentage))
            if payload.billing_percentage is not None
            else None
        ),
        fixed_amount=(
            Decimal(str(payload.fixed_amount)) if payload.fixed_amount is not None else None
        ),
        description=payload.description,
        sort_order=payload.sort_order,
    )
    db.add(milestone)
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="billing_milestone",
        table_name="billing_milestones",
        record_id=str(milestone.id),
        changes={
            "name": {"old": None, "new": milestone.name},
            "billing_type": {"old": None, "new": milestone.billing_type.value},
            "billing_percentage": {
                "old": None,
                "new": float(milestone.billing_percentage) if milestone.billing_percentage is not None else None,
            },
            "fixed_amount": {
                "old": None,
                "new": float(milestone.fixed_amount) if milestone.fixed_amount is not None else None,
            },
        },
    )
    await db.commit()
    await db.refresh(milestone)
    return milestone


@router.patch(
    "/billing-milestones/{milestone_id}", response_model=BillingMilestoneRead
)
async def update_billing_milestone(
    project_id: uuid.UUID,
    milestone_id: uuid.UUID,
    payload: BillingMilestoneUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    project = await get_project_or_404(db, project_id)
    _assert_milestones_writable(project)
    milestone = await _get_milestone_or_404(db, project_id, milestone_id)

    # Milestones referenced by a non-cancelled invoice are immutable — changing
    # the rule after money has been billed would desync the paper trail.
    result = await db.execute(
        select(Invoice).where(
            Invoice.billing_milestone_id == milestone.id,
            Invoice.status != InvoiceStatus.CANCELLED,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot edit a billing milestone that already has an invoice",
        )

    if payload.name is not None:
        existing = await db.execute(
            select(BillingMilestone.id).where(
                BillingMilestone.project_id == project_id,
                BillingMilestone.name == payload.name,
                BillingMilestone.id != milestone.id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="A billing milestone with this name already exists",
            )

    changes = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in ("billing_percentage", "fixed_amount") and value is not None:
            value = Decimal(str(value))
        old = getattr(milestone, field)
        old_serialized = float(old) if isinstance(old, Decimal) else old
        value_serialized = float(value) if isinstance(value, Decimal) else value
        if old_serialized != value_serialized:
            changes[field] = {"old": old_serialized, "new": value_serialized}
        setattr(milestone, field, value)

    # Enforce the one-rule invariant after the merge: percentage milestones
    # carry billing_percentage (fixed_amount stays null) and vice versa. A
    # billing_type switch clears the now-irrelevant field (audited).
    if milestone.billing_type == BillingType.PERCENTAGE:
        if milestone.billing_percentage is None:
            raise HTTPException(
                status_code=400,
                detail="billing_percentage is required when billing_type=percentage",
            )
        if milestone.fixed_amount is not None:
            if milestone.fixed_amount != Decimal("0"):
                changes["fixed_amount"] = {
                    "old": float(milestone.fixed_amount),
                    "new": None,
                }
            milestone.fixed_amount = None
    else:  # FIXED_AMOUNT
        if milestone.fixed_amount is None:
            raise HTTPException(
                status_code=400,
                detail="fixed_amount is required when billing_type=fixed_amount",
            )
        if milestone.billing_percentage is not None:
            if milestone.billing_percentage != Decimal("0"):
                changes["billing_percentage"] = {
                    "old": float(milestone.billing_percentage),
                    "new": None,
                }
            milestone.billing_percentage = None

    await db.flush()
    if changes:
        await record_audit(
            db,
            user_id=admin.id,
            action="billing_milestone_update",
            table_name="billing_milestones",
            record_id=str(milestone.id),
            changes=changes,
        )
    await db.commit()
    await db.refresh(milestone)
    return milestone


@router.post(
    "/billing-milestones/{milestone_id}/complete",
    response_model=BillingMilestoneRead,
)
async def complete_billing_milestone(
    project_id: uuid.UUID,
    milestone_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """Mark a billing milestone completed — the eligibility gate for generating
    its invoice. COMPLETED is terminal (a completed milestone cannot be
    re-opened, matching the append-only doctrine)."""
    project = await get_project_or_404(db, project_id)
    _assert_milestones_writable(project)
    milestone = await _get_milestone_or_404(db, project_id, milestone_id)

    if milestone.status == BillingMilestoneStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Billing milestone is already completed")

    now = datetime.now(timezone.utc)
    milestone.status = BillingMilestoneStatus.COMPLETED
    milestone.completed_at = now
    milestone.completed_by = admin.id
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="billing_milestone_completed",
        table_name="billing_milestones",
        record_id=str(milestone.id),
        changes={
            "status": {"old": BillingMilestoneStatus.NOT_STARTED.value, "new": BillingMilestoneStatus.COMPLETED.value},
            "completed_at": {"old": None, "new": now.isoformat()},
            "completed_by": {"old": None, "new": str(admin.id)},
        },
    )
    await db.commit()
    await db.refresh(milestone)
    return milestone


# --- Invoices / payment requests -------------------------------------------


def _serialize_invoice(invoice: Invoice, project: Project) -> Invoice:
    return _attach_read_fields(invoice, project)


def _serialize_client_invoice(invoice: Invoice, project: Project) -> InvoiceClientRead:
    return InvoiceClientRead.model_validate(_attach_read_fields(invoice, project))


@router.get("/invoices", response_model=list[InvoiceRead | InvoiceClientRead])
async def list_invoices(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Invoices for a project. Admin/procurement get the full shape; a client
    gets only their own project's payment requests in the restricted shape
    (no notes/external/budget fields); supervisors get 403 — finance is not
    a supervisor surface."""
    project = await get_project_or_404(db, project_id)
    if user.role in _FINANCE_READ_ROLES:
        full_view = True
    elif user.role == UserRole.CLIENT:
        await assert_can_view_project(db, user, project)  # archived -> 404 for non-admin
        full_view = False
    else:
        raise HTTPException(
            status_code=403,
            detail="Role 'site_supervisor' is not permitted to view invoices",
        )

    result = await db.execute(
        select(Invoice)
        .where(Invoice.project_id == project_id)
        .order_by(Invoice.created_at.desc())
    )
    invoices = result.scalars().all()
    if full_view:
        return [_serialize_invoice(i, project) for i in invoices]
    return [_serialize_client_invoice(i, project) for i in invoices]


@router.get(
    "/invoices/{invoice_id}", response_model=InvoiceRead | InvoiceClientRead
)
async def get_invoice(
    project_id: uuid.UUID,
    invoice_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_or_404(db, project_id)
    if user.role in _FINANCE_READ_ROLES:
        full_view = True
    elif user.role == UserRole.CLIENT:
        await assert_can_view_project(db, user, project)
        full_view = False
    else:
        raise HTTPException(
            status_code=403,
            detail="Role 'site_supervisor' is not permitted to view invoices",
        )

    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.project_id == project_id)
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if full_view:
        return _serialize_invoice(invoice, project)
    return _serialize_client_invoice(invoice, project)


@router.post(
    "/invoices", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED
)
async def create_invoice(
    project_id: uuid.UUID,
    payload: InvoiceCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
    idem: Annotated[IdempotencyGuard, Depends(get_idempotency_guard)],
):
    """Generate an invoice from a COMPLETED billing milestone.

    Protected by an Idempotency-Key: a retry of an already-committed request
    replays the original invoice instead of generating a duplicate. The project
    row lock serializes invoice-number allocation; the partial unique index
    (billing_milestone_id) WHERE status <> 'CANCELLED' is the DB double-billing
    backstop for requests without a key.
    """
    if idem.replay is not None:
        return idem.replay

    project = await get_project_for_update(db, project_id)
    _assert_invoicing_active(project)

    result = await db.execute(
        select(BillingMilestone).where(
            BillingMilestone.id == payload.billing_milestone_id,
            BillingMilestone.project_id == project_id,
        )
    )
    milestone = result.scalar_one_or_none()
    if milestone is None:
        raise HTTPException(status_code=404, detail="Billing milestone not found")
    if milestone.status != BillingMilestoneStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail="Billing milestone must be completed before generating an invoice",
        )

    existing = await db.execute(
        select(Invoice.id).where(
            Invoice.billing_milestone_id == milestone.id,
            Invoice.status != InvoiceStatus.CANCELLED,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail="An invoice already exists for this billing milestone",
        )

    seq = await next_invoice_seq(db, project.id)
    amount = milestone_amount(project, milestone)
    due_date = payload.due_date or default_due_date(_today())
    invoice = Invoice(
        project_id=project.id,
        invoice_number=invoice_number_for(project.project_code, seq),
        billing_milestone_id=milestone.id,
        milestone_name=milestone.name,
        amount=float(amount),
        status=InvoiceStatus.DRAFT,
        due_date=due_date,
        notes=payload.notes,
    )
    db.add(invoice)
    try:
        await db.flush()
    except IntegrityError:
        # Partial unique index (billing_milestone_id) WHERE status <> 'CANCELLED':
        # the DB-level double-billing backstop for two concurrent no-key requests
        # that both passed the app-level check before either committed.
        raise HTTPException(
            status_code=409,
            detail="An invoice already exists for this billing milestone",
        ) from None

    await record_audit(
        db,
        user_id=admin.id,
        action="invoice_create",
        table_name="invoices",
        record_id=str(invoice.id),
        changes={
            "invoice_number": {"old": None, "new": invoice.invoice_number},
            "billing_milestone_id": {"old": None, "new": str(milestone.id)},
            "milestone_name": {"old": None, "new": milestone.name},
            "amount": {"old": None, "new": float(amount)},
            "status": {"old": None, "new": InvoiceStatus.DRAFT.value},
            "due_date": {"old": None, "new": due_date.isoformat()},
        },
    )

    _attach_read_fields(invoice, project)
    await idem.finish(
        db, status_code=status.HTTP_201_CREATED, response_model=InvoiceRead, obj=invoice
    )
    await db.commit()
    await db.refresh(invoice)
    _attach_read_fields(invoice, project)
    return invoice


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceRead)
async def issue_invoice(
    project_id: uuid.UUID,
    invoice_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """DRAFT -> SENT: the invoice is issued/sent to the client (audited, actor
    + timestamp recorded)."""
    project = await get_project_for_update(db, project_id)
    _assert_invoicing_active(project)
    invoice = await _get_invoice_locked(db, project_id, invoice_id)

    if invoice.status != InvoiceStatus.DRAFT:
        raise HTTPException(
            status_code=400, detail="Only DRAFT invoices can be issued"
        )

    now = datetime.now(timezone.utc)
    invoice.status = InvoiceStatus.SENT
    invoice.issued_at = now
    invoice.issued_by = admin.id
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="invoice_issue",
        table_name="invoices",
        record_id=str(invoice.id),
        changes={
            "status": {"old": InvoiceStatus.DRAFT.value, "new": InvoiceStatus.SENT.value},
            "issued_at": {"old": None, "new": now.isoformat()},
            "issued_by": {"old": None, "new": str(admin.id)},
        },
    )
    await db.commit()
    await db.refresh(invoice)
    _attach_read_fields(invoice, project)
    return invoice


@router.post("/invoices/{invoice_id}/mark-paid", response_model=InvoiceRead)
async def mark_invoice_paid(
    project_id: uuid.UUID,
    invoice_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """SENT -> PAID: record that the client paid this invoice (audited)."""
    project = await get_project_for_update(db, project_id)
    _assert_invoicing_active(project)
    invoice = await _get_invoice_locked(db, project_id, invoice_id)

    if invoice.status != InvoiceStatus.SENT:
        raise HTTPException(status_code=400, detail="Only SENT invoices can be marked paid")

    now = datetime.now(timezone.utc)
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = now
    invoice.paid_by = admin.id
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="invoice_paid",
        table_name="invoices",
        record_id=str(invoice.id),
        changes={
            "status": {"old": InvoiceStatus.SENT.value, "new": InvoiceStatus.PAID.value},
            "paid_at": {"old": None, "new": now.isoformat()},
            "paid_by": {"old": None, "new": str(admin.id)},
        },
    )
    await db.commit()
    await db.refresh(invoice)
    _attach_read_fields(invoice, project)
    return invoice


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceRead)
async def cancel_invoice(
    project_id: uuid.UUID,
    invoice_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """DRAFT|SENT -> CANCELLED: void the invoice. Terminal — no re-open. A
    cancelled invoice frees its billing milestone for a re-issue. No hard
    delete path exists for invoices."""
    project = await get_project_for_update(db, project_id)
    _assert_invoicing_active(project)
    invoice = await _get_invoice_locked(db, project_id, invoice_id)

    if invoice.status not in (InvoiceStatus.DRAFT, InvoiceStatus.SENT):
        raise HTTPException(
            status_code=400,
            detail="Only DRAFT or SENT invoices can be cancelled",
        )

    now = datetime.now(timezone.utc)
    old_status = invoice.status
    invoice.status = InvoiceStatus.CANCELLED
    invoice.cancelled_at = now
    invoice.cancelled_by = admin.id
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="invoice_cancelled",
        table_name="invoices",
        record_id=str(invoice.id),
        changes={
            "status": {"old": old_status.value, "new": InvoiceStatus.CANCELLED.value},
            "cancelled_at": {"old": None, "new": now.isoformat()},
            "cancelled_by": {"old": None, "new": str(admin.id)},
        },
    )
    await db.commit()
    await db.refresh(invoice)
    _attach_read_fields(invoice, project)
    return invoice
