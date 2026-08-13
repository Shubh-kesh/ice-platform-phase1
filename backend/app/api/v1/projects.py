import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_idempotency_guard, require_role
from app.api.project_access import (
    assert_can_view_project,
    assert_not_client,
    assert_project_writable,
    can_access_archived,
    get_project_for_update,
    get_project_or_404,
)
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.health import HealthOverride
from app.models.project import Project, ProjectAssignment, ProjectStatus
from app.models.user import User, UserRole
from app.schemas.health import (
    HealthDimensionRead,
    HealthOverallRead,
    HealthOverrideCreate,
    HealthOverrideSummaryRead,
    ProjectHealthRead,
)
from app.schemas.project import (
    AssignmentCreate,
    ProjectClientRead,
    ProjectCreate,
    ProjectRead,
    ProjectReadRestricted,
    ProjectUpdate,
)
from app.schemas.user import UserRead
from app.services.health import (
    ProjectHealthState,
    compute_health,
    load_health_contexts,
)
from app.services.projects import generate_project_code
from app.services.idempotency import IdempotencyGuard
from app.services.notifications import notify_project_assigned

router = APIRouter(prefix="/projects", tags=["projects"])

admin_only = require_role(UserRole.ADMIN)

# Allocation attempts for one project_code before giving up on the uniqueness
# conflict (each attempt gets a freshly regenerated code).
MAX_PROJECT_CODE_ATTEMPTS = 5

# Only supervisors and clients are granted per-project access — admin and
# procurement already see every project by role (documented in
# ProjectAssignment).
_ASSIGNABLE_ROLES = (UserRole.SITE_SUPERVISOR, UserRole.CLIENT)

# Roles that may see internal monetary figures (budget_total/budget_spent).
_MONEY_ROLES = (UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)


def _serialize_project(
    project: Project, user_role: UserRole
) -> ProjectRead | ProjectReadRestricted | ProjectClientRead:
    """Role-scoped project serialization (M3 no-money slice + M6 client shape).

    The health payload (`GET .../health`) is the source of truth for colors;
    these project reads simply stop leaking money/internal attribution to the
    roles that must not see it. Clients get the tight ProjectClientRead shape
    (M6) — no budgets, no manual health columns, no lifecycle attribution.
    """
    if user_role == UserRole.CLIENT:
        return ProjectClientRead.model_validate(project)
    if full_view_roles(user_role):
        return ProjectRead.model_validate(project)
    return ProjectReadRestricted.model_validate(project)


def full_view_roles(role: UserRole) -> bool:
    return role in _MONEY_ROLES


async def _select_projects(
    db: AsyncSession, user: User, include_archived: bool
) -> list[Project]:
    """Shared project listing for `/projects` and `/projects/health`."""
    base = select(Project)
    if not (include_archived and can_access_archived(user)):
        base = base.where(Project.status != ProjectStatus.ARCHIVED)

    if user.role in _MONEY_ROLES:
        result = await db.execute(base.order_by(Project.created_at.desc()))
    else:
        base = base.join(ProjectAssignment, ProjectAssignment.project_id == Project.id)
        result = await db.execute(
            base.where(ProjectAssignment.user_id == user.id).order_by(Project.created_at.desc())
        )
    return list(result.scalars().all())


def _health_read(
    project: Project, state: ProjectHealthState, include_overrides: bool
) -> ProjectHealthRead:
    """Map the services-layer health state onto the wire schema."""
    def _dimension(
        rating, effective, data_sufficient
    ) -> HealthDimensionRead:
        return HealthDimensionRead(
            value=rating.value,
            effective=effective,
            rated=rating.rated,
            reasons=rating.reasons,
            data_sufficient=data_sufficient,
        )

    now = datetime.now(timezone.utc)
    override_summaries = (
        [
            HealthOverrideSummaryRead(
                id=o.id,
                project_id=o.project_id,
                applied_to=o.applied_to,
                value=o.value,
                reason=o.reason,
                set_by=o.set_by,
                created_at=o.created_at,
                expires_at=o.expires_at,
                revoked_at=o.revoked_at,
                revoked_by=o.revoked_by,
                active=o.revoked_at is None
                and (o.expires_at is None or o.expires_at > now),
            )
            for o in state.active_overrides
        ]
        if include_overrides
        else []
    )

    return ProjectHealthRead(
        project_id=project.id,
        project_code=project.project_code,
        status=project.status,
        frozen=state.frozen,
        timeline=_dimension(state.timeline, state.effective_timeline, state.timeline.rated),
        budget=_dimension(state.budget, state.effective_budget, state.budget.rated),
        safety=_dimension(state.safety, state.effective_safety, state.safety.rated),
        overall=HealthOverallRead(
            value=state.overall.value,
            effective=state.effective_overall,
            rated=state.overall.rated,
            reasons=state.overall.reasons,
            basis=state.overall.basis,
        ),
        data_sufficiency={
            "timeline": state.timeline.rated,
            "budget": state.budget.rated,
            "safety": state.safety.rated,
        },
        overrides=override_summaries,
    )


@router.get("", response_model=list[ProjectRead | ProjectReadRestricted | ProjectClientRead])
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

    Responses are role-scoped: admin/proc get full budget figures, supervisors
    get the no-money shape, and clients get the tight M6 client shape (no
    budgets, no internal health columns, no lifecycle attribution).
    """
    projects = await _select_projects(db, user, include_archived)
    return [_serialize_project(p, user.role) for p in projects]


@router.get("/health", response_model=list[ProjectHealthRead])
async def list_projects_health(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    include_archived: bool = False,
):
    """Command Center roll-up: computed + effective health for every visible
    project. Same visibility/archived rules as `GET /projects`. The payload
    never carries money, so supervisors can see it in full — only the override
    history (admin/procurement) is withheld. Clients are 403 (M6: computed
    health is an internal management signal, not part of the client portal).

    Declared BEFORE `GET /{project_id}` so the `health` literal is never
    shadowed by the UUID path param (regression-tested in test_health.py).
    """
    assert_not_client(user)
    projects = await _select_projects(db, user, include_archived)
    contexts = await load_health_contexts(db, [p.id for p in projects])
    today = datetime.now(timezone.utc).date()
    include_overrides = user.role in _MONEY_ROLES
    return [
        _health_read(p, compute_health(p, contexts[p.id], today), include_overrides)
        for p in projects
    ]


@router.get("/{project_id}/health", response_model=ProjectHealthRead)
async def get_project_health(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Single-project health (project-scoped via shared visibility helpers).

    Clients are 403 (M6: computed health + its reasons/basis are internal
    management signals — the client portal shows progress instead).
    """
    assert_not_client(user)
    project = await get_project_or_404(db, project_id)
    if project.status == ProjectStatus.ARCHIVED and not can_access_archived(user):
        raise HTTPException(status_code=404, detail="Project not found")
    await assert_can_view_project(db, user, project)

    today = datetime.now(timezone.utc).date()
    context = (await load_health_contexts(db, [project.id]))[project.id]
    return _health_read(
        project,
        compute_health(project, context, today),
        include_overrides=user.role in _MONEY_ROLES,
    )


@router.get("/{project_id}", response_model=ProjectRead | ProjectReadRestricted | ProjectClientRead)
async def get_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_or_404(db, project_id)
    if project.status == ProjectStatus.ARCHIVED and not can_access_archived(user):
        raise HTTPException(status_code=404, detail="Project not found")
    await assert_can_view_project(db, user, project)
    return _serialize_project(project, user.role)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
    idem: Annotated[IdempotencyGuard, Depends(get_idempotency_guard)],
):
    """Create a DRAFT project; project_code is auto-generated.

    Protected by an Idempotency-Key: a retry of an already-committed create
    replays the original project instead of allocating a second one (with a
    fresh code, an audit entry and all the follow-on state that anchors to it).
    """
    if idem.replay is not None:
        return idem.replay

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

            await idem.finish(
                db, status_code=status.HTTP_201_CREATED, response_model=ProjectRead, obj=project
            )
            await db.commit()
            return project
        except IntegrityError:
            # The project_code (or any other) uniqueness conflict — the whole
            # attempt (row + audit + idempotency claim) is rolled back; the
            # loop regenerates the code and reclaims the key before retrying.
            await db.rollback()
            await idem.reclaim(db)

    raise HTTPException(
        status_code=409,
        detail="Could not allocate a unique project code. Please retry.",
    )


@router.patch("/{project_id}", response_model=ProjectRead | ProjectReadRestricted)
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
    return _serialize_project(project, user.role)


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


# --- Health overrides (Phase 3 M3) -----------------------------------------
# The only manual health write in the system. ADMIN-only, reason-mandatory,
# single-active-per-target (auto-revokes the previous active override for the
# same applied_to), optional expiry, soft revoke (never hard-delete), fully
# audited. Overrides never modify computed results — they only shade the
# `effective` verdict while the `computed` verdict always stays visible.


def _override_summary(override: HealthOverride, now: datetime) -> HealthOverrideSummaryRead:
    return HealthOverrideSummaryRead(
        id=override.id,
        project_id=override.project_id,
        applied_to=override.applied_to,
        value=override.value,
        reason=override.reason,
        set_by=override.set_by,
        created_at=override.created_at,
        expires_at=override.expires_at,
        revoked_at=override.revoked_at,
        revoked_by=override.revoked_by,
        active=override.revoked_at is None
        and (override.expires_at is None or override.expires_at > now),
    )


@router.get("/{project_id}/health-overrides", response_model=list[HealthOverrideSummaryRead])
async def list_health_overrides(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """Admin-only history of every override ever set for the project
    (including revoked/expired ones — append-only record)."""
    await get_project_or_404(db, project_id)
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(HealthOverride)
        .where(HealthOverride.project_id == project_id)
        .order_by(HealthOverride.created_at.desc())
    )
    return [_override_summary(o, now) for o in result.scalars()]


@router.post(
    "/{project_id}/health-overrides",
    response_model=HealthOverrideSummaryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_health_override(
    project_id: uuid.UUID,
    payload: HealthOverrideCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """Admin sets a manual verdict for one target. Any prior active override for
    the same (project, applied_to) is soft-revoked in the same transaction —
    the partial unique index keeps single-active a DB guarantee."""
    project = await get_project_or_404(db, project_id)
    # ARCHIVED is read-only — no new overrides (consistent with every write path).
    assert_project_writable(project)

    now = datetime.now(timezone.utc)

    # Auto-revoke every prior NON-revoked override for this target — expired
    # but un-revoked rows included — so the new row never collides with the
    # uq_health_overrides_active_per_target partial index (which only checks
    # revoked_at IS NULL). Expired-but-un-revoked rows are already inert for
    # the effective verdict; this cleans them up atomically with the new one.
    prior_result = await db.execute(
        select(HealthOverride)
        .where(
            HealthOverride.project_id == project_id,
            HealthOverride.applied_to == payload.applied_to,
            HealthOverride.revoked_at.is_(None),
        )
        .with_for_update()
    )
    for prior in prior_result.scalars():
        prior.revoked_at = now
        prior.revoked_by = admin.id
        await record_audit(
            db,
            user_id=admin.id,
            action="health_override_revoked",
            table_name="health_overrides",
            record_id=str(prior.id),
            changes={
                "applied_to": prior.applied_to.value,
                "value": prior.value.value,
                "reason": prior.reason,
                "revoked_at": now.isoformat(),
            },
        )

    expires_at = (
        now + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None
    )
    override = HealthOverride(
        project_id=project_id,
        applied_to=payload.applied_to,
        value=payload.value,
        reason=payload.reason,
        set_by=admin.id,
        expires_at=expires_at,
    )
    db.add(override)
    try:
        await db.flush()
    except IntegrityError:
        # Lost a race against another concurrent override for the same target —
        # the whole transaction (including any prior revocation) rolls back.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active health override already exists for this target.",
        ) from None

    await record_audit(
        db,
        user_id=admin.id,
        action="health_override",
        table_name="health_overrides",
        record_id=str(override.id),
        changes={
            "applied_to": payload.applied_to.value,
            "value": payload.value.value,
            "reason": payload.reason,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    await db.commit()
    await db.refresh(override)
    return _override_summary(override, datetime.now(timezone.utc))


@router.delete(
    "/{project_id}/health-overrides/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_health_override(
    project_id: uuid.UUID,
    override_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    """Admin soft-revokes an override — the row is never hard-deleted."""
    await get_project_or_404(db, project_id)
    result = await db.execute(
        select(HealthOverride).where(
            HealthOverride.id == override_id,
            HealthOverride.project_id == project_id,
        )
    )
    override = result.scalar_one_or_none()
    if override is None:
        raise HTTPException(status_code=404, detail="Health override not found")
    if override.revoked_at is not None:
        raise HTTPException(status_code=400, detail="Health override is already revoked")

    now = datetime.now(timezone.utc)
    override.revoked_at = now
    override.revoked_by = admin.id
    await db.flush()

    await record_audit(
        db,
        user_id=admin.id,
        action="health_override_revoked",
        table_name="health_overrides",
        record_id=str(override.id),
        changes={
            "applied_to": override.applied_to.value,
            "value": override.value.value,
            "reason": override.reason,
            "revoked_at": now.isoformat(),
        },
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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

    # M13: notify the newly assigned supervisor/client, atomically with the grant.
    await notify_project_assigned(db, project_id, payload.user_id, project.name)

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