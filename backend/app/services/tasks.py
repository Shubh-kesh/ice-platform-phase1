"""
Task validation + scheduling domain logic (Phase 3 M7 + M12).

M7 closes the two write-path gaps left after M2:
  * date-order was only enforced on create (TaskCreate's model_validator), so
    partial updates could move start/end dates until end_date < start_date;
  * depends_on_id was only validated on create (same-project existence), so
    updates could repoint a task at itself, another project's task, a missing
    row, or form a dependency cycle (A -> B -> A).

M12 adds deterministic, push-only Finish-to-Start scheduling on top: when a
task's dates change, dependent tasks are shifted forward (only) so that
`successor.start >= predecessor.end + 1 calendar day` always holds. The
schedule recomputes on every task mutation inside the project row lock; it is
idempotent (a repeat run changes nothing) and never pulls tasks backward.

Routes own auth/audit; this module owns the invariants. Checks are pure or
single-query, and the API serializes task writes per project via the project
row lock (get_project_for_update) so cycle detection and scheduling are
race-free.
"""
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task

DATE_ORDER_DETAIL = "end_date must be on or after start_date"
DEPENDENCY_MISSING_DETAIL = "depends_on_id must reference a task in the same project"
SELF_DEPENDENCY_DETAIL = "A task cannot depend on itself"
CYCLE_DETAIL = "This dependency would create a cycle"


@dataclass(frozen=True)
class ScheduleShift:
    """One automatically-shifted dependent task produced by apply_schedule.

    `caused_by_task_id` is the immediate predecessor whose moved end date
    forced the shift (used for audit attribution only).
    """

    task_id: uuid.UUID
    old_start: date
    old_end: date
    new_start: date
    new_end: date
    caused_by_task_id: uuid.UUID | None


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


def apply_schedule(tasks: list[Task]) -> list[ScheduleShift]:
    """Push-only Finish-to-Start scheduling over a project's full task set.

    Constraint: for every task with a predecessor,
    `start_date >= predecessor.end_date + 1 calendar day`.

    Semantics (owner-approved M12 decisions):
      * forward-only — tasks are never pulled backward;
      * minimum required shift only — duration is preserved and only the
        smallest forward delta needed to satisfy the constraint is applied;
      * transitive — shifts propagate through the dependency chain to a
        forward-only fixpoint;
      * idempotent — a schedule that already satisfies all constraints yields
        no shifts, and re-running over the same state changes nothing;
      * deterministic — the least fixpoint is unique (monotone forward-only
        push), independent of processing order; processing uses a stable order.

    Mutates the passed ORM Task objects in place (the caller commits them in
    the same locked transaction) and returns one ScheduleShift per task whose
    dates actually changed, with the pre-shift values and the immediate
    predecessor that forced the shift.

    Precondition: the graph is acyclic (M7 guarantees it via the API). The
    fixpoint loop is bounded by the task count + 1 passes; exceeding that
    bound means a cycle slipped through and is raised loudly instead of
    looping forever.
    """
    if not tasks:
        return []

    by_id = {task.id: task for task in tasks}
    predecessors = predecessor_map(tasks)
    snapshot = {
        task.id: (task.start_date, task.end_date) for task in tasks
    }
    # Stable processing order for determinism (list already small + flat).
    ordered = sorted(
        tasks, key=lambda t: (t.sort_order, t.created_at, t.id)
    )

    max_passes = len(tasks) + 1
    changed = True
    passes = 0
    while changed:
        changed = False
        passes += 1
        if passes > max_passes:
            # Defensive: a cycle (or pathological graph) would otherwise push
            # dates forward forever. Should never fire because M7 rejects
            # cycles before scheduling runs.
            raise RuntimeError("Dependency cycle detected during scheduling")
        for task in ordered:
            dep_id = predecessors.get(task.id)
            if dep_id is None:
                continue
            predecessor = by_id.get(dep_id)
            if predecessor is None:
                # FK ON DELETE SET NULL should have cleared this edge; treat a
                # dangling edge as no constraint and keep the task's dates.
                continue
            min_start = predecessor.end_date + timedelta(days=1)
            if task.start_date < min_start:
                delta = (min_start - task.start_date).days
                task.start_date = min_start
                task.end_date = task.end_date + timedelta(days=delta)
                changed = True

    shifts: list[ScheduleShift] = []
    for task in tasks:
        old_start, old_end = snapshot[task.id]
        new_start, new_end = task.start_date, task.end_date
        if (old_start, old_end) != (new_start, new_end):
            shifts.append(
                ScheduleShift(
                    task_id=task.id,
                    old_start=old_start,
                    old_end=old_end,
                    new_start=new_start,
                    new_end=new_end,
                    caused_by_task_id=task.depends_on_id,
                )
            )
    return shifts
