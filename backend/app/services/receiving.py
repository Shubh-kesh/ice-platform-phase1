"""
Thin services layer for PO receiving (Phase 5, M15).

Mirrors the finance/inventory/purchase-orders service modules: pure domain
math, no request/auth/audit/locking concerns. Routes own the transaction
(locks, validation wiring, audit, notifications, idempotency); this module
owns:

  * remaining quantity          (quantity - received_quantity)
  * the over-receipt guard      (received + incoming > quantity -> reject)
  * receipt amount derivation   (round(qty x unit_price, 2), ROUND_HALF_UP —
    reuses purchase_orders.line_total so money rounding never diverges)
  * PO status derivation        (PARTIALLY_RECEIVED / RECEIVED)
"""
from decimal import Decimal
from typing import Sequence

from app.models.purchase_order import POStatus
from app.services.purchase_orders import line_total


def remaining_quantity(quantity: Decimal, received_quantity: Decimal) -> Decimal:
    """Unreceived balance of a PO line."""
    return quantity - received_quantity


def over_receiving(quantity: Decimal, received_quantity: Decimal, incoming: Decimal) -> bool:
    """True when applying `incoming` would push the line past its ordered quantity."""
    return received_quantity + incoming > quantity


def receipt_line_total(quantity_received: Decimal, unit_price: Decimal) -> Decimal:
    """Server-derived receipt line amount — round(qty x price, 2), ROUND_HALF_UP.

    Identical to purchase_orders.line_total so the money quantum is the same
    everywhere money is derived.
    """
    return line_total(quantity_received, unit_price)


def derive_received_status(
    lines: Sequence[tuple[Decimal, Decimal]],
) -> POStatus:
    """PO status after a receipt: RECEIVED when every line is fully received,
    otherwise PARTIALLY_RECEIVED.

    The caller guarantees at least one line was received in this request and
    the PO was APPROVED/PARTIALLY_RECEIVED, so a fully-received set can only
    reach RECEIVED.
    """
    if all(received >= quantity for quantity, received in lines):
        return POStatus.RECEIVED
    return POStatus.PARTIALLY_RECEIVED
