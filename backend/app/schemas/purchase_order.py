"""Pydantic request/response contracts for purchase orders (Phase 5, M14).

Money is server-derived: the client supplies unit prices and quantities on
lines; `line_total`/`subtotal`/`tax_amount` are computed server-side and only
`total_amount` (the stored denormalized value) survives from the backend
calculation. No client-supplied total is ever trusted.
"""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.finance import CostCode
from app.models.purchase_order import POStatus


# --- PO lines ----------------------------------------------------------------


class POLineBase(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=50)
    unit_price: float = Field(ge=0)
    cost_code: CostCode


class POLineCreate(POLineBase):
    pass


class POLineUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=255)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    unit_price: float | None = Field(default=None, ge=0)
    cost_code: CostCode | None = None


class POLineRead(POLineBase):
    """Line as serialized to admin/procurement. `line_total` is derived on read
    (quantity x unit_price, ROUND_HALF_UP to 2dp) — never a stored column."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purchase_order_id: uuid.UUID
    line_total: float
    created_at: datetime
    updated_at: datetime


# --- Purchase orders ---------------------------------------------------------


class PurchaseOrderCreate(BaseModel):
    """Create a PO (optionally with nested lines). The client never supplies
    money totals — every line total and the PO total derive server-side.
    `tax_rate` is optional, 0-100, applied to the whole PO."""

    vendor_id: uuid.UUID
    order_date: date | None = None
    expected_delivery: date | None = None
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[POLineCreate] = []


class PurchaseOrderUpdate(BaseModel):
    """DRAFT header fields only (DRAFT-only edits; money/quantities never
    client-derivable). status is never PATCH-able — lifecycle moves through the
    dedicated transition endpoints."""

    vendor_id: uuid.UUID | None = None
    order_date: date | None = None
    expected_delivery: date | None = None
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=2000)


class PurchaseOrderReject(BaseModel):
    rejected_reason: str = Field(min_length=1, max_length=2000)


class PurchaseOrderRead(BaseModel):
    """Admin/procurement view of a PO. `project_code`, `vendor_name`,
    `subtotal` and `tax_amount` are transient (attached on read); `total_amount`
    is the stored denormalized value (subtotal + tax)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    po_number: str
    project_id: uuid.UUID
    project_code: str
    vendor_id: uuid.UUID
    vendor_name: str
    status: POStatus
    order_date: date
    expected_delivery: date | None
    tax_rate: float | None
    subtotal: float
    tax_amount: float
    total_amount: float
    notes: str | None
    created_by: uuid.UUID | None
    submitted_at: datetime | None
    submitted_by: uuid.UUID | None
    approved_at: datetime | None
    approved_by: uuid.UUID | None
    rejected_at: datetime | None
    rejected_by: uuid.UUID | None
    rejected_reason: str | None
    cancelled_at: datetime | None
    cancelled_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    lines: list[POLineRead]
