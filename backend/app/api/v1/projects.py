import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.api.project_access import assert_can_view_project, get_project_or_404
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.project import Project, ProjectAssignment
from app.models.user import User, UserRole
from app.schemas.project import AssignmentCreate, ProjectCreate, ProjectRead, ProjectUpdate
from app.schemas.user import UserRead

router = APIRouter(prefix="/projects", tags=["projects"])

admin_only = require_role(UserRole.ADMIN)

# Only supervisors and clients are granted per-project access — admin and
# procurement already see every project by role (documented in
# ProjectAssignment).
_ASSIGNABLE_ROLES = (UserRole.SITE_SUPERVISOR, UserRole.CLIENT)


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
    project = await get_project_or_404(db, project_id)
    await assert_can_view_project(db, user, project)
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
    project = await get_project_or_404(db, project_id)

    # Supervisors may only update projects they're assigned to.
    if user.role == UserRole.SITE_SUPERVISOR:
        await assert_can_view_project(db, user, project)

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


async def _get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/{project_id}/assignments", response_model=list[UserRead])
async def list_project_assignments(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(admin_only)],
):
    """Admin-only: the users granted access to this project."""
    await get_project_or_404(db, project_id)
    result = await db.execute(
        select(User)
        .join(ProjectAssignment, ProjectAssignment.user_id == User.id)
        .where(ProjectAssignment.project_id == project_id)
        .order_by(User.full_name)
    )
    return result.scalars().all()


@router.post(
    "/{project_id}/assignments",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_user_to_project(
    project_id: uuid.UUID,
    payload: AssignmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """Admin-only: grant a supervisor/client access to a project."""
    await get_project_or_404(db, project_id)
    user = await _get_user_or_404(db, payload.user_id)

    if user.role not in _ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Only site supervisors and clients can be assigned to projects",
        )

    existing = await db.execute(
        select(ProjectAssignment).where(
            ProjectAssignment.project_id == project_id,
            ProjectAssignment.user_id == payload.user_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="User is already assigned to this project")

    db.add(ProjectAssignment(project_id=project_id, user_id=payload.user_id))
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="assign",
        table_name="project_assignments",
        record_id=str(project_id),
        changes={"user_id": {"old": None, "new": str(payload.user_id)}},
    )

    await db.commit()
    return user


@router.delete("/{project_id}/assignments/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_user_from_project(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """Admin-only: revoke a user's access to a project (takes effect immediately)."""
    await get_project_or_404(db, project_id)

    result = await db.execute(
        select(ProjectAssignment).where(
            ProjectAssignment.project_id == project_id,
            ProjectAssignment.user_id == user_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise HTTPException(status_code=404, detail="User is not assigned to this project")

    await db.delete(assignment)
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="unassign",
        table_name="project_assignments",
        record_id=str(project_id),
        changes={"user_id": {"old": str(user_id), "new": None}},
    )

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
