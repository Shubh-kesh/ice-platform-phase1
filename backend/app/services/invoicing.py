"""
Thin services layer for milestone invoicing (Phase 3, M5).

Mirrors the finance/health service modules: pure domain math, no request/auth/
audit concerns. Routes own authorization and audit; these functions own the
billing calculations so invoice amounts derive from the schedule-of-values
(BillingMilestone rule x Project.budget_total) and NEVER from the job-cost
ledger — job costs are expenditure, invoices are client billing/revenue.

Amount math is Decimal throughout (quantized to 2 dp) so money is never
touched by float arithmetic; the API schemas serialize as float, matching the
M4 job-cost convention.
"""
import datetime
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import BillingMilestone, BillingType, Invoice, InvoiceStatus
from app.models.project import Project

MONEY_QUANTUM = Decimal("0.01")
DEFAULT_DUE_DAYS = 30


def milestone_amount(project: Project, milestone: BillingMilestone) -> Decimal:
    """Invoice amount derived from the milestone billing rule.

    PERCENTAGE -> round(budget_total * pct / 100, 2); FIXED_AMOUNT -> the rule.
    Project.budget_total is the contract value (the schedule-of-values basis);
    job costs never enter this calculation.
    """
    if milestone.billing_type == BillingType.PERCENTAGE:
        if milestone.billing_percentage is None:
            raise ValueError("percentage milestone is missing billing_percentage")
        pct = Decimal(milestone.billing_percentage)
        total = Decimal(project.budget_total)
        return (total * pct / Decimal(100)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    if milestone.billing_type == BillingType.FIXED_AMOUNT:
        if milestone.fixed_amount is None:
            raise ValueError("fixed_amount milestone is missing fixed_amount")
        return Decimal(milestone.fixed_amount).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    raise ValueError(f"unsupported billing_type: {milestone.billing_type!r}")


def invoice_number_for(project_code: str, seq: int) -> str:
    """INV-<project_code>-<seq>, e.g. INV-PRJ-2026-0001-0001."""
    return f"INV-{project_code}-{seq:04d}"


async def next_invoice_seq(db: AsyncSession, project_id) -> int:
    """Next invoice sequence number for a project = current invoice count + 1.

    Safe because the caller invokes it inside a transaction holding the project
    row lock (SELECT ... FOR UPDATE), so concurrent creates serialize and the
    count can't be read before the winner's insert commits. Uniqueness of the
    rendered number is additionally hardened by uq_invoices_invoice_number.
    """
    result = await db.execute(
        select(func.count()).select_from(Invoice).where(Invoice.project_id == project_id)
    )
    return int(result.scalar_one()) + 1


def default_due_date(issued_on: date) -> date:
    """Standard payment terms: due DEFAULT_DUE_DAYS days after issuance."""
    return issued_on + datetime.timedelta(days=DEFAULT_DUE_DAYS)


def derive_overdue(status: InvoiceStatus, due_date: date, today: date) -> bool:
    """OVERDUE is derived on read (never stored): a SENT invoice past due."""
    return status == InvoiceStatus.SENT and due_date < today
