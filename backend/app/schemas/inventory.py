import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.inventory import MovementType


class InventoryItemBase(BaseModel):
    name: str
    unit: str
    reorder_threshold: float | None = Field(default=None, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)


class InventoryItemCreate(InventoryItemBase):
    # Optional opening balance — recorded as an initial "received" movement
    # rather than a bare column write, so the ledger stays the single source
    # of truth for quantity_on_hand.
    opening_quantity: float = Field(default=0, ge=0)


class InventoryItemUpdate(BaseModel):
    name: str | None = None
    unit: str | None = None
    reorder_threshold: float | None = Field(default=None, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)


class InventoryItemRead(InventoryItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    quantity_on_hand: float
    created_at: datetime
    updated_at: datetime


class StockMovementCreate(BaseModel):
    movement_type: MovementType
    quantity: float = Field(gt=0)  # magnitude only — sign is derived from movement_type
    note: str | None = None


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_id: uuid.UUID
    recorded_by: uuid.UUID | None
    movement_type: MovementType
    quantity: float
    po_line_id: uuid.UUID | None
    note: str | None
    created_at: datetime


class InventoryReconciliationRead(BaseModel):
    """One row of the ledger-reconciliation report (item vs its ledger balance)."""

    item_id: uuid.UUID
    project_id: uuid.UUID
    name: str
    unit: str
    quantity_on_hand: float
    ledger_balance: float
    matches: bool
