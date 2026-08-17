"""Field-data tools (W7.3): get_project_tasks, get_daily_site_logs."""
from __future__ import annotations

import uuid
from typing import Any

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from app.ai.context import ActorContext
from app.ai.tools.base import (
    actor_from,
    bound_items,
    current_db,
    get_project_visible,
    load_user,
    safe_tool,
)
from app.models.site_log import DailySiteLog
from app.models.task import Task


@tool
@safe_tool
async def get_project_tasks(
    project_id: uuid.UUID, limit: int = 50, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """List the schedule tasks for a project (name, status, progress, dates).
    Use for schedule questions, 'what tasks are pending', timeline."""
    actor = actor_from(runtime)
    db = current_db()
    user = await load_user(db, actor)
    project = await get_project_visible(db, user, project_id)

    result = await db.execute(
        select(Task)
        .where(Task.project_id == project.id)
        .order_by(Task.sort_order, Task.start_date)
    )
    tasks = list(result.scalars().all())
    rows = [
        {
            "task_id": str(t.id),
            "name": t.name,
            "status": t.status.value,
            "percent_complete": t.percent_complete,
            "start_date": t.start_date.isoformat(),
            "end_date": t.end_date.isoformat(),
        }
        for t in tasks
    ]
    return bound_items(rows, total_count=len(rows), limit=limit)


@tool
@safe_tool
async def get_daily_site_logs(
    project_id: uuid.UUID, limit: int = 20, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """List recent daily site logs for a project (date, work summary, issues,
    weather). Use for 'what happened on site', daily log questions."""
    actor = actor_from(runtime)
    db = current_db()
    user = await load_user(db, actor)
    project = await get_project_visible(db, user, project_id)

    result = await db.execute(
        select(DailySiteLog)
        .where(DailySiteLog.project_id == project.id)
        .order_by(DailySiteLog.log_date.desc())
    )
    logs = list(result.scalars().all())
    rows = [
        {
            "log_id": str(log.id),
            "log_date": log.log_date.isoformat(),
            "work_summary": log.work_summary,
            "issues": log.issues,
            "weather": log.weather,
        }
        for log in logs
    ]
    return bound_items(rows, total_count=len(rows), limit=limit)
