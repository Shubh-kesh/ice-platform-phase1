"""
Shared project-access helpers.

Originally lived as private functions inside api/v1/projects.py; pulled out
here so the Phase 2 sub-resource endpoints (tasks, daily logs, inventory —
all scoped to a project) can enforce the exact same visibility rule without
duplicating it four times.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectAssignment
from app.models.user import User, UserRole


async def get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def assert_can_view_project(db: AsyncSession, user: User, project: Project) -> None:
    if user.role in (UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER):
        return
    result = await db.execute(
        select(ProjectAssignment).where(
            ProjectAssignment.project_id == project.id,
            ProjectAssignment.user_id == user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="You don't have access to this project")
