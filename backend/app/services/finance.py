"""
Thin services layer for finance roll-up logic (Phase 3, M4).

Mirrors the inventory services module: pure domain math, no request/auth/audit
concerns. Routes own authorization and audit; these functions own the ledger
roll-up so budget_spent can be derived from job_costs instead of hand-typed.

budget_spent on Project is a denormalized running total (like quantity_on_hand);
the job_costs rows are the authoritative ledger. Every job-cost mutation calls
refresh_budget_spent() in the same transaction, so the two never disagree for
long. The budget endpoint also re-computes from the ledger on read, so a stale
Project.budget_spent (e.g. from a legacy manual PATCH) is surfaced immediately.
"""
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import JobCost
from app.models.project import Project


async def sum_job_costs(db: AsyncSession, project_id: uuid.UUID) -> Decimal:
    """Total of every job-cost ledger row for a project."""
    result = await db.execute(
        select(func.coalesce(func.sum(JobCost.amount), 0)).where(
            JobCost.project_id == project_id
        )
    )
    return Decimal(result.scalar_one())


async def _budget_by_cost_code(
    db: AsyncSession, project_id: uuid.UUID
) -> dict[str, Decimal]:
    """Roll-up of job costs grouped by cost code."""
    rows = (
        await db.execute(
            select(JobCost.cost_code, func.sum(JobCost.amount))
            .where(JobCost.project_id == project_id)
            .group_by(JobCost.cost_code)
            .order_by(JobCost.cost_code)
        )
    ).all()
    return {row[0].value: Decimal(row[1]) for row in rows}


async def budget_rollup(db: AsyncSession, project: Project) -> dict[str, Any]:
    """Computed budget report for a project:
    total budget, spent (from the ledger), remaining, and per-cost-code split.
    """
    spent = await sum_job_costs(db, project.id)
    total = Decimal(project.budget_total)
    return {
        "project_id": project.id,
        "budget_total": total,
        "budget_spent": spent,
        "budget_remaining": total - spent,
        "by_cost_code": await _budget_by_cost_code(db, project.id),
    }


async def refresh_budget_spent(db: AsyncSession, project: Project) -> Decimal:
    """Recompute Project.budget_spent from the job-cost ledger and persist it.

    Called inside the same transaction as any job-cost mutation so the
    denormalized total tracks the ledger atomically.
    """
    spent = await sum_job_costs(db, project.id)
    project.budget_spent = float(spent)
    return spent