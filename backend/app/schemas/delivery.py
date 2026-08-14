"""Pydantic request/response contracts for PO deliveries/receiving (Phase 5, M15).

Receiving is evidence-first: the client supplies a reference, an optional note
/ photo_reference, and per-line positive quantities + a target inventory item.
Money is never client-supplied — `unit_price` / `line_total` are derived
server-side from the PO line and snapshotted on the receipt row.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeliveryLineCreate(BaseModel):
    """One PO line to receive. `quantity` is a positive magnitude only; the
    sign (RECEIVED +1), the unit price and the line total are server-derived."""

    po_line_id: uuid.UUID
    quantity: float = Field(gt=0)
    inventory_item_id: uuid.UUID


class DeliveryCreate(BaseModel):
    """A verified receipt: evidence reference + one or more PO lines."""

    reference: str = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=2000)
    photo_reference: str | None = Field(default=None, max_length=500)
    lines: list[DeliveryLineCreate] = Field(min_length=1)


class DeliveryLineRead(BaseModel):
    """Receipt line as serialized to admin/procurement. `description`/`unit` are
    transient (attached on read from the PO line); amounts are snapshots."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    delivery_id: uuid.UUID
    po_line_id: uuid.UUID
    inventory_item_id: uuid.UUID
    quantity_received: float
    unit_price: float
    line_total: float
    created_at: datetime
    description: str | None = None
    unit: str | None = None


class DeliveryRead(BaseModel):
    """Flat receipt shape (mapped columns + transient `line_count`/
    `po_status_after`).

    Deliberately does NOT serialize `lines` through the ORM relationship: the
    M8 `IdempotencyGuard.finish()` refresh would expire a loaded relationship
    (async lazy-load -> MissingGreenlet, the M14 lesson). Line detail is served
    by `GET .../deliveries/{delivery_id}`. `line_count`/`po_status_after` are
    attached by the receive handler before idempotency finalization (setattr
    doctrine); they default to safe values so the schema is serializable even
    before the handler attaches them.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    purchase_order_id: uuid.UUID
    reference: str
    note: str | None
    photo_reference: str | None
    verified_by: uuid.UUID | None
    verified_at: datetime
    created_by: uuid.UUID | None
    created_at: datetime
    line_count: int = 0
    po_status_after: str | None = None


class DeliveryDetailRead(DeliveryRead):
    """Full receipt shape for `GET .../deliveries/{delivery_id}`: the flat
    `DeliveryRead` fields plus the per-line detail (description/unit attached
    on read from the PO line). Served by a plain read endpoint — never through
    `IdempotencyGuard.finish()` — so the `lines` relationship is safe here."""

    lines: list[DeliveryLineRead]
