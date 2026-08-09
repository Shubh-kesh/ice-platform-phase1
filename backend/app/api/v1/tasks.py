"""
Gantt/timeline endpoints — a flat, ordered list of tasks per project.

Read access follows the same rule as the project itself (assigned users +
admin/procurement see it). Write access is admin or the assigned site
supervisor, matching how project updates are already scoped.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.api.project_access import assert_can_view_project, get_project_or_404
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.task import Task
from app.models.user import User, UserRole
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])

write_roles = require_role(UserRole.ADMIN, UserRole.SITE_SUPERVISOR)


async def _assert_can_write(db: AsyncSession, user: User, project_id: uuid.UUID) -> None:
    """Admin can write to any project; a supervisor only to ones they're assigned to."""
    project = await get_project_or_404(db, project_id)
    if user.role == UserRole.SITE_SUPERVISOR:
        await assert_can_view_project(db, user, project)


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

    if payload.depends_on_id is not None:
        dep = await db.execute(
            select(Task).where(Task.id == payload.depends_on_id, Task.project_id == project_id)
        )
        if dep.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="depends_on_id must reference a task in the same project")

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

    changes = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        old_value = getattr(task, field, None)
        if old_value != value:
            changes[field] = {"old": old_value, "new": value}
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
