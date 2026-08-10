import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.api.project_access import (
    assert_can_view_project,
    assert_project_writable,
    can_access_archived,
    get_project_for_update,
    get_project_or_404,
)
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.project import Project, ProjectAssignment, ProjectStatus
from app.models.user import User, UserRole
from app.schemas.project import AssignmentCreate, ProjectCreate, ProjectRead, ProjectUpdate
from app.schemas.user import UserRead
from app.services.projects import generate_project_code

router = APIRouter(prefix="/projects", tags=["projects"])

admin_only = require_role(UserRole.ADMIN)

# Allocation attempts for one project_code before giving up on the uniqueness
# conflict (each attempt gets a freshly regenerated code).
MAX_PROJECT_CODE_ATTEMPTS = 5

# Only supervisors and clients are granted per-project access — admin and
# procurement already see every project by role (documented in
# ProjectAssignment).
_ASSIGNABLE_ROLES = (UserRole.SITE_SUPERVISOR, UserRole.CLIENT)


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    include_archived: bool = False,
):
    """
    Admin and Procurement Manager get the full bird's-eye view. Site
    Supervisor and Client only see projects they're assigned to. ARCHIVED
    projects are excluded from normal lists; admin/proc can opt back in with
    ?include_archived=true. COMPLETED projects remain visible (reporting).
    """
    base = select(Project)
    if not (include_archived and can_access_archived(user)):
        base = base.where(Project.status != ProjectStatus.ARCHIVED)

    if user.role in (UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER):
        result = await db.execute(base.order_by(Project.created_at.desc()))
    else:
        base = base.join(ProjectAssignment, ProjectAssignment.project_id == Project.id)
        result = await db.execute(
            base.where(ProjectAssignment.user_id == user.id).order_by(Project.created_at.desc())
        )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_or_404(db, project_id)
    if project.status == ProjectStatus.ARCHIVED and not can_access_archived(user):
        raise HTTPException(status_code=404, detail="Project not found")
    await assert_can_view_project(db, user, project)
    return project


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    # The max()-based code draw can hand two concurrent creators the same
    # PRJ-YYYY-####; the DB unique constraint (uq_projects_project_code)
    # resolves it. The loser rolls back and retries with a freshly
    # regenerated code instead of surfacing an avoidable 500.
    for _ in range(MAX_PROJECT_CODE_ATTEMPTS):
        project = Project(
            **payload.model_dump(),
            project_code=await generate_project_code(db),
            status=ProjectStatus.DRAFT,
            created_by=admin.id,
        )
        db.add(project)
        try:
            await db.flush()  # Get project.id + code before recording audit

            # Record audit trail
            await record_audit(
                db,
                user_id=admin.id,
                action="create",
                table_name="projects",
                record_id=str(project.id),
                changes={
                    "name": {"old": None, "new": project.name},
                    "project_code": {"old": None, "new": project.project_code},
                    "status": {"old": None, "new": project.status.value},
                },
            )

            await db.commit()
            await db.refresh(project)
            return project
        except IntegrityError:
            # The project_code (or any other) uniqueness conflict — the whole
            # attempt (row + audit) is rolled back; loop regenerates the code.
            await db.rollback()

    raise HTTPException(
        status_code=409,
        detail="Could not allocate a unique project code. Please retry.",
    )


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.SITE_SUPERVISOR))],
):
    project = await get_project_or_404(db, project_id)
    if project.status == ProjectStatus.ARCHIVED and not can_access_archived(user):
        raise HTTPException(status_code=404, detail="Project not found")

    # Supervisors may only update projects they're assigned to.
    if user.role == UserRole.SITE_SUPERVISOR:
        await assert_can_view_project(db, user, project)

    # ARCHIVED projects are read-only — no project data changes.
    assert_project_writable(project)

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


# --- Lifecycle transitions (Phase 3 M10) -----------------------------------
# status is never a PATCH field: projects move states only through these
# admin-only, fully audited actions. No hard-delete exists for any state.


async def _transition(
    db: AsyncSession, project_id: uuid.UUID, admin: User, action: str, new_status: ProjectStatus
) -> Project:
    # Row lock (SELECT ... FOR UPDATE, the M1/M4 pattern) so two concurrent
    # transitions serialize: the guard below re-reads the post-commit status
    # of whichever transition won the lock, so only one lifecycle decision is
    # made against a given state and the audit chain never contradicts itself.
    project = await get_project_for_update(db, project_id)
    now = datetime.now(timezone.utc)
    old_status = project.status

    if new_status == ProjectStatus.ACTIVE:
        if old_status not in (ProjectStatus.DRAFT, ProjectStatus.PLANNING, ProjectStatus.ON_HOLD):
            raise HTTPException(
                status_code=400,
                detail="Only DRAFT/PLANNING/ON_HOLD projects can be activated",
            )
    elif new_status == ProjectStatus.COMPLETED:
        if old_status != ProjectStatus.ACTIVE:
            raise HTTPException(status_code=400, detail="Only ACTIVE projects can be completed")
        project.completed_at = now
        project.completed_by = admin.id
        project.percent_complete = 100
    elif new_status == ProjectStatus.ARCHIVED:
        if old_status not in (ProjectStatus.ACTIVE, ProjectStatus.COMPLETED):
            raise HTTPException(
                status_code=400, detail="Only ACTIVE or COMPLETED projects can be archived"
            )
        project.archived_at = now
        project.archived_by = admin.id
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported transition to {new_status.value}")

    project.status = new_status
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action=action,
        table_name="projects",
        record_id=str(project.id),
        changes={"status": {"old": old_status.value, "new": new_status.value}},
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.post("/{project_id}/activate", response_model=ProjectRead)
async def activate_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    return await _transition(db, project_id, admin, "activate", ProjectStatus.ACTIVE)


@router.post("/{project_id}/complete", response_model=ProjectRead)
async def complete_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    return await _transition(db, project_id, admin, "complete", ProjectStatus.COMPLETED)


@router.post("/{project_id}/archive", response_model=ProjectRead)
async def archive_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    return await _transition(db, project_id, admin, "archive", ProjectStatus.ARCHIVED)


@router.post("/{project_id}/restore", response_model=ProjectRead)
async def restore_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    project = await get_project_for_update(db, project_id)
    if project.status != ProjectStatus.ARCHIVED:
        raise HTTPException(status_code=400, detail="Only archived projects can be restored")

    now = datetime.now(timezone.utc)
    # Restore to ACTIVE (or back to COMPLETED if it was completed before
    # being archived, preserving the completed reporting state).
    restored_status = (
        ProjectStatus.COMPLETED if project.completed_at is not None else ProjectStatus.ACTIVE
    )
    project.status = restored_status
    project.restored_at = now
    project.restored_by = admin.id
    project.archived_at = None
    project.archived_by = None
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="restore",
        table_name="projects",
        record_id=str(project.id),
        changes={"status": {"old": ProjectStatus.ARCHIVED.value, "new": restored_status.value}},
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
    project = await get_project_or_404(db, project_id)
    assert_project_writable(project)
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
    project = await get_project_or_404(db, project_id)
    assert_project_writable(project)

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