"""
Task validation domain logic (Phase 3, M7).

Closes the two write-path gaps left after M2:
  * date-order was only enforced on create (TaskCreate's model_validator), so
    partial updates could move start/end dates until end_date < start_date;
  * depends_on_id was only validated on create (same-project existence), so
    updates could repoint a task at itself, another project's task, a missing
    row, or form a dependency cycle (A -> B -> A).

Routes own auth/audit; this module owns the invariants. Checks are pure or
single-query, and the API serializes task writes per project via the project
row lock (get_project_for_update) so cycle detection is race-free.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task

DATE_ORDER_DETAIL = "end_date must be on or after start_date"
DEPENDENCY_MISSING_DETAIL = "depends_on_id must reference a task in the same project"
SELF_DEPENDENCY_DETAIL = "A task cannot depend on itself"
CYCLE_DETAIL = "This dependency would create a cycle"


def validate_task_dates(start_date, end_date) -> None:
    """Reject end_date < start_date on the effective (merged) task dates.

    Called on update after merging partial fields with the persisted row;
    create already enforces this in the schema.
    """
    if end_date < start_date:
        raise HTTPException(status_code=422, detail=DATE_ORDER_DETAIL)


async def validate_dependency(
    db: AsyncSession,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    depends_on_id: uuid.UUID | None,
) -> None:
    """Same-project existence + not-self for a depends_on_id change.

    `task_id` is the task being edited (None on create), so an update that
    points a task at itself is rejected here rather than surfacing as a cycle.
    """
    if depends_on_id is None:
        return
    if task_id is not None and depends_on_id == task_id:
        raise HTTPException(status_code=400, detail=SELF_DEPENDENCY_DETAIL)
    dep = await db.execute(
        select(Task).where(Task.id == depends_on_id, Task.project_id == project_id)
    )
    if dep.scalar_one_or_none() is None:
        raise HTTPException(status_code=400, detail=DEPENDENCY_MISSING_DETAIL)


async def get_project_tasks(db: AsyncSession, project_id: uuid.UUID) -> list[Task]:
    """Every task in the project in one query (task lists are small and flat)."""
    result = await db.execute(select(Task).where(Task.project_id == project_id))
    return list(result.scalars().all())


def detect_dependency_cycle(
    predecessors: dict[uuid.UUID, uuid.UUID | None], start_id: uuid.UUID
) -> bool:
    """True if following depends_on_id from start_id loops back to start_id.

    Adding a single edge A->C creates a cycle iff C's predecessor chain
    reaches A, so one walk from the edited task is sufficient. Iterative and
    bounded by the task count — no recursion, no unbounded loops. `seen`
    also catches a pre-existing cycle anywhere in the chain.
    """
    seen: set[uuid.UUID] = set()
    current: uuid.UUID | None = start_id
    for _ in range(len(predecessors) + 1):
        dep = predecessors.get(current) if current is not None else None
        if dep is None:
            return False
        if dep == start_id or dep in seen:
            return True
        seen.add(dep)
        current = dep
    return True


def predecessor_map(tasks: list[Task]) -> dict[uuid.UUID, uuid.UUID | None]:
    """Collapse tasks to {id: depends_on_id} so the walk can test a proposal
    without mutating ORM objects (a raised HTTPException must not leave a
    half-applied depends_on_id on a session that outlives the request)."""
    return {task.id: task.depends_on_id for task in tasks}
