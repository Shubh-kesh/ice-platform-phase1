"""Pydantic request/response contracts for the finance pillar (Phase 3, M4+)."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.finance import CostCode


# --- Job costs ---


class JobCostBase(BaseModel):
    cost_code: CostCode
    description: str = Field(min_length=1, max_length=1000)
    amount: float = Field(gt=0, description="Always a positive money value")
    incurred_on: date


class JobCostCreate(JobCostBase):
    pass


class JobCostUpdate(BaseModel):
    cost_code: CostCode | None = None
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    amount: float | None = Field(default=None, gt=0)
    incurred_on: date | None = None


class JobCostRead(JobCostBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    created_at: datetime


# --- Budget roll-up ---


class BudgetRollupRead(BaseModel):
    """Computed budget report — budget_total, spent (ledger sum), remaining,
    and the per-cost-code split. Derives budget spending from job_costs rather
    than trusting a hand-typed Project.budget_spent."""

    project_id: uuid.UUID
    budget_total: float
    budget_spent: float
    budget_remaining: float
    by_cost_code: dict[CostCode, float]