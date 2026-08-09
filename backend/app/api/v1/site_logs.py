"""
Daily site log endpoints — an append-only feed a supervisor writes and
anyone with project access can read. No update/delete: like AuditLog, this
is a field record, not something to be edited after the fact.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.api.project_access import assert_can_view_project, get_project_or_404
from app.core.database import get_db
from app.middleware.audit import record_audit
from app.models.site_log import DailySiteLog
from app.models.user import User, UserRole
from app.schemas.site_log import DailySiteLogCreate, DailySiteLogRead

router = APIRouter(prefix="/projects/{project_id}/site-logs", tags=["site-logs"])

write_roles = require_role(UserRole.ADMIN, UserRole.SITE_SUPERVISOR)


@router.get("", response_model=list[DailySiteLogRead])
async def list_site_logs(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    project = await get_project_or_404(db, project_id)
    await assert_can_view_project(db, user, project)

    result = await db.execute(
        select(DailySiteLog)
        .where(DailySiteLog.project_id == project_id)
        .order_by(DailySiteLog.log_date.desc())
    )
    return result.scalars().all()


@router.post("", response_model=DailySiteLogRead, status_code=status.HTTP_201_CREATED)
async def create_site_log(
    project_id: uuid.UUID,
    payload: DailySiteLogCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(write_roles)],
):
    project = await get_project_or_404(db, project_id)
    if user.role == UserRole.SITE_SUPERVISOR:
        await assert_can_view_project(db, user, project)

    log = DailySiteLog(project_id=project_id, created_by=user.id, **payload.model_dump())
    db.add(log)
    await db.flush()

    await record_audit(
        db,
        user_id=user.id,
        action="create",
        table_name="daily_site_logs",
        record_id=str(log.id),
        changes={"log_date": {"old": None, "new": str(log.log_date)}},
    )

    await db.commit()
    await db.refresh(log)
    return log
