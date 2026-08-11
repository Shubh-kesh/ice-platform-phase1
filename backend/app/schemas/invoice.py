"""Pydantic request/response contracts for milestone invoicing (Phase 3, M5)."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.finance import BillingMilestoneStatus, BillingType, InvoiceStatus


# --- Billing milestones (schedule of values) ---


class BillingMilestoneBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    billing_type: BillingType
    billing_percentage: float | None = Field(default=None, gt=0, le=100)
    fixed_amount: float | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=2000)
    sort_order: int = Field(default=0, ge=0)


class BillingMilestoneCreate(BillingMilestoneBase):
    """Create a milestone. Exactly one of billing_percentage (for
    billing_type=percentage) or fixed_amount (for fixed_amount) is required."""

    @model_validator(mode="after")
    def _one_rule(self) -> "BillingMilestoneCreate":
        if self.billing_type == BillingType.PERCENTAGE:
            if self.billing_percentage is None:
                raise ValueError(
                    "billing_percentage is required when billing_type=percentage"
                )
            if self.fixed_amount is not None:
                raise ValueError(
                    "fixed_amount must be null when billing_type=percentage"
                )
        elif self.billing_type == BillingType.FIXED_AMOUNT:
            if self.fixed_amount is None:
                raise ValueError("fixed_amount is required when billing_type=fixed_amount")
            if self.billing_percentage is not None:
                raise ValueError(
                    "billing_percentage must be null when billing_type=fixed_amount"
                )
        return self


class BillingMilestoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    billing_type: BillingType | None = None
    billing_percentage: float | None = Field(default=None, gt=0, le=100)
    fixed_amount: float | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=2000)
    sort_order: int | None = Field(default=None, ge=0)


class BillingMilestoneRead(BillingMilestoneBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: BillingMilestoneStatus
    completed_at: datetime | None
    completed_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


# --- Invoices / payment requests ---


class InvoiceCreate(BaseModel):
    """Generate an invoice from a COMPLETED billing milestone.

    The amount is computed server-side from the milestone rule + the project's
    contract value (budget_total) — clients never supply money values. due_date
    defaults to issuance + 30 days when omitted.
    """

    billing_milestone_id: uuid.UUID
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class InvoiceRead(BaseModel):
    """Admin/procurement view of an invoice. OVERDUE is derived on read
    (status == SENT and due_date passed) — never a stored value."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    project_code: str
    invoice_number: str
    billing_milestone_id: uuid.UUID | None
    milestone_name: str
    amount: float
    status: InvoiceStatus
    overdue: bool
    due_date: date
    notes: str | None
    issued_at: datetime | None
    issued_by: uuid.UUID | None
    paid_at: datetime | None
    paid_by: uuid.UUID | None
    cancelled_at: datetime | None
    cancelled_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class InvoiceClientRead(BaseModel):
    """The ONLY shape a client ever sees for an invoice/payment request.

    Deliberately excludes every internal field: notes, external_ref,
    external_sync_status, and the billing rule (billing_percentage /
    fixed_amount) — the schedule-of-values configuration is internal finance
    data. No budget or job-cost figures appear anywhere in the payload.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    project_code: str
    invoice_number: str
    milestone_name: str
    amount: float
    status: InvoiceStatus
    overdue: bool
    due_date: date
    issued_at: datetime | None
    paid_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
