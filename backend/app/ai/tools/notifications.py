"""Notification tool for the ICE Copilot (AI-1): get_my_notifications."""
from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool
from sqlalchemy import select

from app.ai.context import ActorContext
from app.ai.tools.base import actor_from, bound_items, current_db, safe_tool
from app.models.notification import Notification


@tool
@safe_tool
async def get_my_notifications(
    unread_only: bool = True, limit: int = 20, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """List the current user's own in-app notifications (unread first by
    default). Use for 'what needs my attention', 'notifications'."""
    actor = actor_from(runtime)
    db = current_db()

    stmt = (
        select(Notification)
        .where(Notification.user_id == actor.user_id)
        .order_by(Notification.created_at.desc())
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    result = await db.execute(stmt)
    notifications = list(result.scalars().all())
    rows = [
        {
            "notification_id": str(notification.id),
            "type": (
                notification.type.value
                if hasattr(notification.type, "value")
                else str(notification.type)
            ),
            "title": notification.title,
            "body": notification.body,
            "link": notification.link,
            "project_id": (
                str(notification.project_id) if notification.project_id is not None else None
            ),
            "read": notification.read_at is not None,
            "created_at": (
                notification.created_at.isoformat() if notification.created_at else None
            ),
        }
        for notification in notifications
    ]
    return bound_items(rows, total_count=len(rows), limit=limit)
