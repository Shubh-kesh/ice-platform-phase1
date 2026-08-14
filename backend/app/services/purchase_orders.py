"""
Thin services layer for purchase orders (Phase 5, M14).

Mirrors the finance/invoicing service modules: pure domain math, no request/
auth/audit concerns. Routes own authorization and audit; these functions own
the PO calculations so totals derive from line data server-side and are never
trusted from the client.

Money is Decimal throughout (quantized to 2 dp, ROUND_HALF_UP) — float never
touches money in the calculation. The API schemas serialize as float, matching
the M4 job-cost convention.

Invariants this module enforces (test-pinned):
  * line_total = round(qty x unit_price, 2)
  * subtotal    = SUM(line_total)
  * tax_amount  = round(subtotal x tax_rate / 100, 2) when tax_rate set, else 0
  * total       = subtotal + tax_amount  (stored denormalized on the PO row)
"""
import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.purchase_order import POLine, PurchaseOrder

MONEY_QUANTUM = Decimal("0.01")


def line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Derived line total — round(qty x unit_price, 2)."""
    return (quantity * unit_price).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def tax_amount(subtotal: Decimal, tax_rate: Decimal | None) -> Decimal:
    """Optional PO-level tax: round(subtotal x tax_rate / 100, 2); 0 when unset."""
    if tax_rate is None:
        return Decimal("0")
    return (subtotal * tax_rate / Decimal("100")).quantize(
        MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )


def po_total(subtotal: Decimal, tax_rate: Decimal | None) -> Decimal:
    """total_amount = subtotal + tax_amount."""
    return subtotal + tax_amount(subtotal, tax_rate)


async def po_subtotal_from_lines(db: AsyncSession, purchase_order_id: uuid.UUID) -> Decimal:
    """Sum of per-line derived totals for a PO (each line total quantized)."""
    result = await db.execute(
        select(POLine).where(POLine.purchase_order_id == purchase_order_id)
    )
    lines = result.scalars().all()
    return sum(
        (line_total(line.quantity, line.unit_price) for line in lines),
        Decimal("0"),
    )


async def refresh_po_total(db: AsyncSession, po: PurchaseOrder) -> tuple[Decimal, Decimal]:
    """Recompute the denormalized total_amount from the PO's lines (+ tax) and
    persist it on the PO row. Called inside the same transaction as every
    line create/update/delete and every header PATCH that changes tax_rate, so
    total_amount never drifts from the lines (the M4/M1 running-total doctrine).
    Returns (subtotal, tax_amount)."""
    subtotal = await po_subtotal_from_lines(db, po.id)
    tax = tax_amount(subtotal, po.tax_rate)
    po.total_amount = subtotal + tax
    return subtotal, tax


def po_number_for(project_code: str, seq: int) -> str:
    """PO-<project_code>-<seq:04d>, e.g. PO-PRJ-2026-0001-0001."""
    return f"PO-{project_code}-{seq:04d}"


async def next_po_seq(db: AsyncSession, project_id: uuid.UUID) -> int:
    """Next PO sequence number for a project = current PO count + 1.

    Safe because the caller invokes it inside a transaction holding the project
    row lock (SELECT ... FOR UPDATE), so concurrent creates serialize and the
    count can't be read before the winner's insert commits. Uniqueness of the
    rendered number is additionally hardened by uq_purchase_orders_po_number.
    """
    result = await db.execute(
        select(func.count()).select_from(PurchaseOrder).where(
            PurchaseOrder.project_id == project_id
        )
    )
    return int(result.scalar_one()) + 1
