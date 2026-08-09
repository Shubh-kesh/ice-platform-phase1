"""
Audit log endpoints — admin-only access to immutable audit trails.

Audit logs track all create/update/delete operations for compliance and debugging.
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role, get_current_user
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.schemas.audit import AuditLogRead

router = APIRouter(prefix="/audit", tags=["audit"])

# Admin-only access
admin_only = require_role(UserRole.ADMIN)


@router.get("/logs", response_model=list[AuditLogRead])
async def list_audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(admin_only)],
    table_name: str | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """
    List audit logs (admin-only).

    Optional filters:
    - table_name: Filter by table (e.g., 'users', 'projects')
    - action: Filter by action (e.g., 'create', 'update', 'delete')
    - limit: Max results (default 100, max 1000)
    - offset: Pagination offset (default 0)
    """
    limit = min(limit, 1000)  # Cap at 1000 per request

    query = select(AuditLog)

    if table_name:
        query = query.where(AuditLog.table_name == table_name)
    if action:
        query = query.where(AuditLog.action == action)

    query = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()
