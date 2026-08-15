"""Finance tool for the ICE Copilot (AI-1): get_project_budget."""
from __future__ import annotations

import uuid
from typing import Any

from langchain.tools import ToolRuntime, tool

from app.ai.context import ActorContext
from app.ai.tools.base import (
    actor_from,
    current_db,
    get_project_any,
    require_role,
    safe_tool,
)
from app.models.user import UserRole
from app.services.finance import budget_rollup


@tool
@safe_tool
async def get_project_budget(
    project_id: uuid.UUID, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get the budget roll-up for a project: total, spent, remaining and the
    spend split by cost code. Use for budget questions. Admin and procurement
    only."""
    actor = actor_from(runtime)
    require_role(actor, UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)
    db = current_db()
    project = await get_project_any(db, project_id)
    rollup = await budget_rollup(db, project)
    return {
        "project_id": str(project.id),
        "project_code": project.project_code,
        "budget_total": float(rollup["budget_total"]),
        "budget_spent": float(rollup["budget_spent"]),
        "budget_remaining": float(rollup["budget_remaining"]),
        "by_cost_code": {
            key.value if hasattr(key, "value") else str(key): float(value)
            for key, value in rollup["by_cost_code"].items()
        },
    }
