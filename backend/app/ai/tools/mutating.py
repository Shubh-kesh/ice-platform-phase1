"""W7.4 — controlled ICE mutations behind HumanInTheLoop.

The FIRST low-risk mutating tools: `create_task` and `create_daily_site_log`.

Rules that are NOT duplicated here:
- RBAC / project visibility / IDOR / archived-readonly rules come from the
  SAME `app/api/project_access` helpers + `load_user` the REST routes use.
- Dependency/date validation comes from `app/services/tasks`.
- Audit and transaction semantics mirror the REST routes exactly
  (`record_audit` + schedule-shift auditing + the same commit).

Rules that ARE enforced here (never supplied by the model):
- The authenticated actor is read from `ToolRuntime.context` (ActorContext);
  identity is never a tool argument.
- Hard role gate: admin or site supervisor only (REST `write_roles`).
- HITL is an ADDITIONAL control layer: the model can only PROPOSE a mutation;
  the tool executes only after `HumanInTheLoopMiddleware` receives an explicit
  human decision via the resume endpoint.

These tools are only registered/surfaced when `ICE_AI_MUTATIONS_ENABLED=true`
and only after a human decision, so the default product remains read-only.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from app.ai.context import ActorContext
from fastapi import HTTPException

from app.ai.security import ToolError
from app.ai.tools.base import (
    _raise_as_tool_error,
    actor_from,
    current_db,
    load_user,
    require_role,
    safe_tool,
)
from app.api.project_access import assert_can_view_project, assert_project_writable, get_project_for_update, get_project_or_404
from app.middleware.audit import record_audit
from app.models.site_log import DailySiteLog
from app.models.task import Task
from app.models.user import UserRole
from app.services.notifications import notify_schedule_shift
from app.services.tasks import (
    ScheduleShift,
    apply_schedule,
    get_project_tasks,
    validate_dependency,
    validate_task_dates,
)


async def _audit_schedule_shifts(db, shifts: list[ScheduleShift], actor_id: uuid.UUID) -> None:
    """Audit every automatically-shifted dependent (M12) in the same transaction
    as the schedule change — mirrors the REST create_task route."""
    for shift in shifts:
        await record_audit(
            db,
            user_id=actor_id,
            action="task_schedule_shift",
            table_name="tasks",
            record_id=str(shift.task_id),
            changes={
                "start_date": {
                    "old": shift.old_start.isoformat(),
                    "new": shift.new_start.isoformat(),
                },
                "end_date": {
                    "old": shift.old_end.isoformat(),
                    "new": shift.new_end.isoformat(),
                },
                "caused_by_task_id": (
                    str(shift.caused_by_task_id) if shift.caused_by_task_id else None
                ),
            },
        )


async def _resolve_writable_project(
    db, actor: ActorContext, user, project_id: uuid.UUID
):
    """Admin can write any project; a supervisor only assigned ones. ARCHIVED
    projects are read-only. Mirrors the REST `_assert_can_write`.

    HTTPException is converted to ToolError INSIDE the tool body (not inside
    safe_tool's except-handler) so safe_tool's own except clauses catch it and
    the denial becomes a safe model-visible dict.
    """
    try:
        project = await get_project_for_update(db, project_id)
        if actor.role == UserRole.SITE_SUPERVISOR:
            await assert_can_view_project(db, user, project)
        assert_project_writable(project)
    except HTTPException as exc:  # noqa: PERF203
        _raise_as_tool_error(exc)
    return project


@tool
@safe_tool
async def create_task(
    project_id: uuid.UUID,
    name: str,
    start_date: date,
    end_date: date,
    depends_on_id: uuid.UUID | None = None,
    sort_order: int = 0,
    runtime: ToolRuntime[ActorContext] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Create a new schedule task on a project (requires human approval before
    it runs). Use to add tasks like 'Foundation inspection'. The human must
    approve/edit/reject the proposal first."""
    actor = actor_from(runtime)
    db = current_db()
    user = await load_user(db, actor)
    require_role(actor, UserRole.ADMIN, UserRole.SITE_SUPERVISOR)

    project = await _resolve_writable_project(db, actor, user, project_id)
    try:
        validate_task_dates(start_date, end_date)
        await validate_dependency(db, project.id, task_id=None, depends_on_id=depends_on_id)
    except HTTPException as exc:  # noqa: PERF203
        _raise_as_tool_error(exc)

    task = Task(
        project_id=project.id,
        name=name,
        start_date=start_date,
        end_date=end_date,
        depends_on_id=depends_on_id,
        sort_order=sort_order,
    )
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

    shifts = apply_schedule(await get_project_tasks(db, project.id))
    await _audit_schedule_shifts(db, shifts, user.id)
    if shifts:
        await notify_schedule_shift(db, project.id, len(shifts))

    await db.commit()
    return {
        "ok": True,
        "task_id": str(task.id),
        "name": task.name,
        "status": task.status.value,
        "start_date": task.start_date.isoformat(),
        "end_date": task.end_date.isoformat(),
    }


@tool
@safe_tool
async def create_daily_site_log(
    project_id: uuid.UUID,
    log_date: date,
    work_summary: str,
    issues: str | None = None,
    workers_present: int | None = None,
    weather: str | None = None,
    photo_urls: list[str] | None = None,
    runtime: ToolRuntime[ActorContext] = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Append a daily site log entry for a project (requires human approval
    before it runs). Use to log what happened on site. The human must
    approve/edit/reject the proposal first."""
    actor = actor_from(runtime)
    db = current_db()
    user = await load_user(db, actor)
    require_role(actor, UserRole.ADMIN, UserRole.SITE_SUPERVISOR)

    try:
        project = await get_project_or_404(db, project_id)
        if actor.role == UserRole.SITE_SUPERVISOR:
            await assert_can_view_project(db, user, project)
        assert_project_writable(project)  # ARCHIVED projects are read-only
    except HTTPException as exc:  # noqa: PERF203
        _raise_as_tool_error(exc)

    # The REST route guards double-submits with an Idempotency-Key; the AI
    # path has no header, so reject an identical day explicitly (this feed is
    # append-only — a duplicate (project_id, log_date) is never legitimate).
    existing = await db.execute(
        select(DailySiteLog).where(
            DailySiteLog.project_id == project.id,
            DailySiteLog.log_date == log_date,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ToolError("A daily site log for this date already exists")

    log = DailySiteLog(
        project_id=project.id,
        created_by=user.id,
        log_date=log_date,
        work_summary=work_summary,
        issues=issues,
        workers_present=workers_present,
        weather=weather,
        photo_urls=photo_urls or [],
    )
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
    return {
        "ok": True,
        "log_id": str(log.id),
        "log_date": log.log_date.isoformat(),
        "work_summary": log.work_summary,
    }
