"""
Gantt/timeline endpoints — a flat, ordered list of tasks per project.

Read access follows the same rule as the project itself (assigned users +
admin/procurement see it). Write access is admin or the assigned site
supervisor, matching how project updates are already scoped.
"""
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.api.project_access import (
    assert_can_view_project,
    assert_project_writable,
    get_project_for_update,
    get_project_or_404,
)
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.project import Project
from app.models.task import Task
from app.models.user import User, UserRole
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services.tasks import (
    CYCLE_DETAIL,
    detect_dependency_cycle,
    get_project_tasks,
    predecessor_map,
    validate_dependency,
    validate_task_dates,
)

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])

write_roles = require_role(UserRole.ADMIN, UserRole.SITE_SUPERVISOR)


async def _assert_can_write(db: AsyncSession, user: User, project_id: uuid.UUID) -> Project:
    """Admin can write to any project; a supervisor only to ones they're assigned to.

    ARCHIVED projects are read-only: supervisors are kept out by the view
    check (404, no existence leak) and admin/procurement get 403 here.

    Takes the project row lock (M7) so dependency/cycle validation runs
    against the latest committed task edges — concurrent writes to the same
    project's tasks serialize on this row.
    """
    project = await get_project_for_update(db, project_id)
    if user.role == UserRole.SITE_SUPERVISOR:
        await assert_can_view_project(db, user, project)
    assert_project_writable(project)
    return project


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_or_404(db, project_id)
    await assert_can_view_project(db, user, project)

    result = await db.execute(
        select(Task).where(Task.project_id == project_id).order_by(Task.sort_order, Task.start_date)
    )
    return result.scalars().all()


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    project_id: uuid.UUID,
    payload: TaskCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    await _assert_can_write(db, user, project_id)

    await validate_dependency(db, project_id, task_id=None, depends_on_id=payload.depends_on_id)

    task = Task(project_id=project_id, **payload.model_dump())
    db.add(task)
    await db.flush()

    await record_audit(
        db,
        user_id=user.id,
        action="create",
        table_name="tasks",
        record_id=str(task.id),
        changes={"name": {"old": None, "new": task.name}},
    )

    await db.commit()
    await db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: TaskUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    await _assert_can_write(db, user, project_id)

    result = await db.execute(select(Task).where(Task.id == task_id, Task.project_id == project_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    update_data = payload.model_dump(exclude_unset=True)

    # Validate against the effective (merged) state BEFORE mutating the ORM
    # object — the shared session can outlive a failed request, so a raised
    # HTTPException must never leave a half-applied change behind.
    validate_task_dates(
        update_data.get("start_date", task.start_date),
        update_data.get("end_date", task.end_date),
    )

    if "depends_on_id" in update_data:
        await validate_dependency(db, project_id, task_id=task.id, depends_on_id=update_data["depends_on_id"])
        # Adding a single edge A->C creates a cycle iff C's chain reaches A,
        # so test the proposal without touching the session.
        predecessors = predecessor_map(await get_project_tasks(db, project_id))
        predecessors[task.id] = update_data["depends_on_id"]
        if detect_dependency_cycle(predecessors, task.id):
            raise HTTPException(status_code=400, detail=CYCLE_DETAIL)

    changes = {}
    for field, value in update_data.items():
        old_value = getattr(task, field, None)
        old_serialized = str(old_value) if isinstance(old_value, (uuid.UUID, date)) else old_value
        value_serialized = str(value) if isinstance(value, (uuid.UUID, date)) else value
        if old_serialized != value_serialized:
            changes[field] = {"old": old_serialized, "new": value_serialized}
        # Assign the raw typed value to the ORM attribute; audit uses the
        # serialized copy above (audit_logs.changes is JSONB).
        setattr(task, field, value)

    await db.flush()

    if changes:
        await record_audit(
            db,
            user_id=user.id,
            action="update",
            table_name="tasks",
            record_id=str(task.id),
            changes=changes,
        )

    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    await _assert_can_write(db, user, project_id)

    result = await db.execute(select(Task).where(Task.id == task_id, Task.project_id == project_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    await record_audit(
        db,
        user_id=user.id,
        action="delete",
        table_name="tasks",
        record_id=str(task.id),
        changes={"name": {"old": task.name, "new": None}},
    )

    await db.delete(task)
    await db.commit()
