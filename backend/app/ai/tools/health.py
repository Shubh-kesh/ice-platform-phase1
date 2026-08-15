"""Project health tool for the ICE Copilot (AI-1): get_project_health."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from langchain.tools import ToolRuntime, tool

from app.ai.context import ActorContext
from app.ai.tools.base import (
    actor_from,
    assert_not_client_role,
    current_db,
    get_project_visible,
    load_user,
    safe_tool,
)
from app.services.health import compute_health, load_health_contexts


def _dim(rating: Any, effective: Any) -> dict[str, Any]:
    """Compact a dimension's computed verdict + reasons."""
    return {
        "value": rating.value.value,
        "effective": effective.value,
        "rated": rating.rated,
        "reasons": rating.reasons,
    }


def _overall(state: Any) -> dict[str, Any]:
    return {
        "value": state.overall.value.value,
        "effective": state.effective_overall.value,
        "rated": state.overall.rated,
        "reasons": state.overall.reasons,
        "basis": state.overall.basis,
    }


@tool
@safe_tool
async def get_project_health(
    project_id: uuid.UUID, runtime: ToolRuntime[ActorContext] = None  # type: ignore[assignment]
) -> dict[str, Any]:
    """Get the computed health of a project: overall, timeline, budget and
    safety verdicts with human-readable reasons. Use for 'why is X unhealthy',
    'is X on track', 'which projects need attention'."""
    actor = actor_from(runtime)
    db = current_db()
    user = await load_user(db, actor)
    # M6: computed health is an internal management signal — clients are denied.
    assert_not_client_role(actor)
    project = await get_project_visible(db, user, project_id)

    today = datetime.now(timezone.utc).date()
    context = (await load_health_contexts(db, [project.id]))[project.id]
    state = compute_health(project, context, today)
    return {
        "project_id": str(project.id),
        "project_code": project.project_code,
        "status": project.status.value,
        "frozen": state.frozen,
        "overall": _overall(state),
        "timeline": _dim(state.timeline, state.effective_timeline),
        "budget": _dim(state.budget, state.effective_budget),
        "safety": _dim(state.safety, state.effective_safety),
    }
