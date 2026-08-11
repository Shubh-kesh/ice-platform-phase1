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

from app.models.project import Project, ProjectAssignment, ProjectStatus
from app.models.user import User, UserRole


async def get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def get_project_for_update(db: AsyncSession, project_id: uuid.UUID) -> Project:
    """Load a project with a PostgreSQL row lock (SELECT ... FOR UPDATE).

    Serializes concurrent read-modify-write against the same project row so
    each writer's guard/derivation decision is made against the latest
    committed state — the same lock inventory movements (M1) and job-cost
    mutations (M4) take, held until the caller's transaction commits.
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def can_access_archived(user: User) -> bool:
    """Only admin/procurement ever see ARCHIVED projects."""
    return user.role in (UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)


def assert_project_writable(project: Project) -> None:
    """Reject any write to an ARCHIVED project — archives are read-only.

    Called after project *visibility* is resolved in each write path, so a
    supervisor/client still receives 404 (an archived project's existence
    must not leak) and only the roles that can see the project
    (admin/procurement) reach this 403. The lifecycle transition endpoints
    (activate/complete/archive/restore) are the deliberate exception and do
    not call this guard.
    """
    if project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=403, detail="Archived projects are read-only")


def assert_not_client(user: User) -> None:
    """Internal management surfaces are off-limits to the CLIENT role (M6).

    The CLIENT portal boundary: clients may see their assigned projects'
    schedule, site updates and issued payment requests only. Computed health
    (internal management signal), the inventory/procurement ledger and other
    internal surfaces are 403 for the client role regardless of assignment —
    the supervisor keeps the existing project-access behavior, so this guard
    is applied per-endpoint on the surfaces clients must never reach.
    """
    if user.role == UserRole.CLIENT:
        raise HTTPException(
            status_code=403,
            detail="Role 'client' is not permitted to view this data",
        )


async def assert_can_view_project(db: AsyncSession, user: User, project: Project) -> None:
    if user.role in (UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER):
        return
    # ARCHIVED projects are invisible to everyone except admin/procurement —
    # return 404 (not 403) so their existence isn't leaked.
    if project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=404, detail="Project not found")
    result = await db.execute(
        select(ProjectAssignment).where(
            ProjectAssignment.project_id == project.id,
            ProjectAssignment.user_id == user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="You don't have access to this project")