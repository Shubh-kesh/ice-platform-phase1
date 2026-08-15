"""Project tools for the ICE Copilot (AI-1): list_projects, get_project."""
from __future__ import annotations

import uuid
from typing import Any

from langchain.tools import ToolRuntime, tool

from app.ai.context import ActorContext
from app.ai.tools.base import (
    actor_from,
    bound_items,
    compact_project,
    current_db,
    get_project_visible,
    list_visible_projects,
    load_user,
    safe_tool,
)


@tool
@safe_tool
async def list_projects(
    include_archived: bool = False, limit: int = 50, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """List the construction projects visible to the current user, with status
    and progress. Admin and procurement see every project (and may include
    archived ones); site supervisors and clients only see assigned projects.
    Use for 'which projects', 'show my projects', 'what needs attention'."""
    actor = actor_from(runtime)
    db = current_db()
    user = await load_user(db, actor)

    from app.api.v1.projects import _serialize_project

    projects = await list_visible_projects(db, user, include_archived)
    rows = [
        compact_project(_serialize_project(project, actor.role).model_dump(mode="json"))
        for project in projects
    ]
    return bound_items(rows, total_count=len(rows), limit=limit)


@tool
@safe_tool
async def get_project(
    project_id: uuid.UUID, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get detail for one construction project, role-scoped. Includes the site
    address, client name, schedule and progress. Use when a specific project is
    named."""
    actor = actor_from(runtime)
    db = current_db()
    user = await load_user(db, actor)
    project = await get_project_visible(db, user, project_id)

    from app.api.v1.projects import _serialize_project

    dump = _serialize_project(project, actor.role).model_dump(mode="json")
    return compact_project(dump, detail=True)
