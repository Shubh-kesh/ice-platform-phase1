"""
Thin services layer for project lifecycle (Phase 3, M10).

Owns the pure domain rules for project codes and lifecycle transitions so
route handlers only concern themselves with auth/audit plumbing — the same
pattern as app/services/finance.py (M4).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectStatus


def next_project_code(project_code: str) -> str:
    """Increment a PRJ-YYYY-#### code by the sequence portion."""
    prefix, seq = project_code.rsplit("-", 1)
    return f"{prefix}-{int(seq) + 1:04d}"


async def generate_project_code(db: AsyncSession) -> str:
    """Return a unique project code for the current year.

    Format: PRJ-YYYY-####. The highest existing sequence for the year is
    derived from the max LF of project_code for the prefix PRJ-YYYY; if none
    exists the first code is PRJ-YYYY-0001. Uniqueness is additionally
    hardened by the uq_projects_project_code constraint at commit time.
    """
    prefix = "PRJ" + "-" + str(datetime.now(timezone.utc).year)
    result = await db.execute(
        select(Project.project_code)
        .where(Project.project_code.like(f"{prefix}-%"))
        .order_by(Project.project_code.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    if last is None:
        return f"{prefix}-0001"
    return next_project_code(last)


async def archive_project(db: AsyncSession, project: Project, actor_id: uuid.UUID) -> Project:
    """ARCHIVED is the terminal state: read-only, hidden from normal lists.

    No hard delete — history (job costs, inventory, site logs, assignments)
    remains queryable in reporting for admins.
    """
    project.status = ProjectStatus.ARCHIVED
    project.archived_at = datetime.now(timezone.utc)
    project.archived_by = actor_id
    return project