"""
Finance endpoints — job costing (Phase 3, M4) and, later, invoicing (M5).

Job costs form the ledger from which Project.budget_spent is derived. Every
create/update/delete re-computes budget_spent against the ledger in the same
transaction (the inventory quantity_on_hand pattern); the budget roll-up
endpoint reports spent/remaining/total with a per-cost-code split.

Write access: Admin and Procurement Manager. Read access for the cost list and
the budget roll-up is likewise restricted to Admin/Procurement — job-cost line
items and amounts are budget figures and must not be exposed to clients or
supervisors (ROADMAP: never leak budget_* outside admin/proc). Concurrency:
project rows are locked (SELECT ... FOR UPDATE) on every mutation so concurrent
job-cost writes serialize and budget_spent never drifts from the ledger.
"""
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.api.project_access import assert_project_writable, get_project_or_404
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.finance import CostCode, JobCost
from app.models.project import Project
from app.models.user import User, UserRole
from app.schemas.finance import BudgetRollupRead, JobCostCreate, JobCostRead, JobCostUpdate
from app.services.finance import budget_rollup, refresh_budget_spent

router = APIRouter(prefix="/projects/{project_id}", tags=["finance"])

write_roles = require_role(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)
budget_roles = require_role(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)


async def _get_project_locked(db: AsyncSession, project_id: uuid.UUID) -> Project:
    """Load the project with a PostgreSQL row lock (SELECT ... FOR UPDATE).

    Project.budget_spent is a denormalized running total recomputed from the
    job-cost ledger; locking the project row serializes concurrent writes to
    the same project so two transactions can't both read the SUM before either
    commits and clobber the total (the M1 inventory row-lock pattern).
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_job_cost_or_404(
    db: AsyncSession, project_id: uuid.UUID, cost_id: uuid.UUID
) -> JobCost:
    result = await db.execute(
        select(JobCost).where(JobCost.id == cost_id, JobCost.project_id == project_id)
    )
    cost = result.scalar_one_or_none()
    if cost is None:
        raise HTTPException(status_code=404, detail="Job cost not found")
    return cost


@router.get("/job-costs", response_model=list[JobCostRead])
async def list_job_costs(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(budget_roles)],
):
    """Job-cost ledger listing. Restricted to Admin/Procurement along with the
    budget roll-up: cost line items are budget figures, so clients/supervisors
    must not read them (ROADMAP: never leak budget_* outside admin/proc)."""
    await get_project_or_404(db, project_id)

    result = await db.execute(
        select(JobCost)
        .where(JobCost.project_id == project_id)
        .order_by(JobCost.incurred_on.desc(), JobCost.created_at.desc())
    )
    return result.scalars().all()


@router.post("/job-costs", response_model=JobCostRead, status_code=status.HTTP_201_CREATED)
async def create_job_cost(
    project_id: uuid.UUID,
    payload: JobCostCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    project = await _get_project_locked(db, project_id)
    assert_project_writable(project)  # ARCHIVED projects are read-only

    cost = JobCost(project_id=project_id, **payload.model_dump())
    db.add(cost)
    await db.flush()

    # Keep the denormalized budget_spent tracking the ledger (same txn).
    await refresh_budget_spent(db, project)

    await record_audit(
        db,
        user_id=user.id,
        action="create",
        table_name="job_costs",
        record_id=str(cost.id),
        changes={"cost_code": {"old": None, "new": cost.cost_code.value}, "amount": {"old": None, "new": float(cost.amount)}},
    )

    await db.commit()
    await db.refresh(cost)
    return cost


@router.patch("/job-costs/{cost_id}", response_model=JobCostRead)
async def update_job_cost(
    project_id: uuid.UUID,
    cost_id: uuid.UUID,
    payload: JobCostUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    cost = await _get_job_cost_or_404(db, project_id, cost_id)
    project = await _get_project_locked(db, project_id)
    assert_project_writable(project)  # ARCHIVED projects are read-only

    changes = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        old = getattr(cost, field)
        old_serialized = old
        if isinstance(old_serialized, CostCode):
            old_serialized = old_serialized.value
        if isinstance(value, CostCode):
            value_serialized = value.value
        else:
            value_serialized = value
        old_serialized = float(old_serialized) if isinstance(old_serialized, Decimal) else old_serialized
        value_serialized = float(value_serialized) if isinstance(value_serialized, Decimal) else value_serialized
        if old_serialized != value_serialized:
            changes[field] = {"old": old_serialized, "new": value_serialized}
        # Assign the raw (typed) value to the ORM attribute so cost_code stays a
        # CostCode enum, not the drifted .value string; audit uses the serialized
        # copy above.
        setattr(cost, field, value)

    await db.flush()

    if changes:
        await refresh_budget_spent(db, project)
        await record_audit(
            db,
            user_id=user.id,
            action="update",
            table_name="job_costs",
            record_id=str(cost.id),
            changes=changes,
        )

    await db.commit()
    await db.refresh(cost)
    return cost


@router.delete("/job-costs/{cost_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job_cost(
    project_id: uuid.UUID,
    cost_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    cost = await _get_job_cost_or_404(db, project_id, cost_id)
    project = await _get_project_locked(db, project_id)
    assert_project_writable(project)  # ARCHIVED projects are read-only

    await record_audit(
        db,
        user_id=user.id,
        action="delete",
        table_name="job_costs",
        record_id=str(cost.id),
        changes={"amount": {"old": float(cost.amount), "new": None}, "cost_code": {"old": cost.cost_code.value, "new": None}},
    )

    await db.delete(cost)
    await db.flush()
    await refresh_budget_spent(db, project)

    await db.commit()
    return None


@router.get("/budget", response_model=BudgetRollupRead)
async def get_budget_rollup(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(budget_roles)],
):
    """Computed budget report derived from the job-cost ledger (admin/proc only)."""
    project = await get_project_or_404(db, project_id)
    return await budget_rollup(db, project)