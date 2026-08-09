import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.project import Project, ProjectAssignment
from app.models.user import User, UserRole
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """
    Admin and Procurement Manager get the full 15-project bird's-eye view.
    Site Supervisor and Client only see projects they're assigned to.
    """
    if user.role in (UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER):
        result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    else:
        result = await db.execute(
            select(Project)
            .join(ProjectAssignment, ProjectAssignment.project_id == Project.id)
            .where(ProjectAssignment.user_id == user.id)
            .order_by(Project.created_at.desc())
        )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = await _get_project_or_404(db, project_id)
    await _assert_can_view(db, user, project)
    return project


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(require_role(UserRole.ADMIN))],
):
    project = Project(**payload.model_dump())
    db.add(project)
    await db.flush()  # Get project.id before recording audit

    # Record audit trail
    await record_audit(
        db,
        user_id=admin.id,
        action="create",
        table_name="projects",
        record_id=str(project.id),
        changes={"name": {"old": None, "new": project.name}},
    )

    await db.commit()
    await db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.SITE_SUPERVISOR))],
):
    project = await _get_project_or_404(db, project_id)

    # Supervisors may only update projects they're assigned to.
    if user.role == UserRole.SITE_SUPERVISOR:
        await _assert_can_view(db, user, project)

    # Track changes for audit log
    changes = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        old_value = getattr(project, field, None)
        if old_value != value:
            changes[field] = {"old": old_value, "new": value}
        setattr(project, field, value)

    await db.flush()

    # Record audit trail if changes were made
    if changes:
        await record_audit(
            db,
            user_id=user.id,
            action="update",
            table_name="projects",
            record_id=str(project.id),
            changes=changes,
        )

    await db.commit()
    await db.refresh(project)
    return project


async def _get_project_or_404(db: AsyncSession, project_id: uuid.UUID) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _assert_can_view(db: AsyncSession, user: User, project: Project) -> None:
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
