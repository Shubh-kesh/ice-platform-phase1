"""
Shared helpers for the ICE Copilot read-only tools (AI-1).

Every tool enforces hard deterministic authorization internally and returns
compact, stable, LLM-friendly structured data. Controlled failures are raised
as ToolForbidden / ToolNotFound and converted (by the `safe_tool` wrapper) into
safe error dicts the model can read — raw exceptions or SQL errors never reach
the model.
"""
from __future__ import annotations

import functools
import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Awaitable, Callable, TypeVar, cast

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context import ActorContext, current_session
from app.ai.security import ToolError, ToolForbidden, ToolNotFound
from app.api.project_access import (
    assert_can_view_project,
    can_access_archived,
    get_project_or_404,
)
from app.core.config import settings
from app.models.project import Project, ProjectStatus
from app.models.user import User, UserRole

logger = logging.getLogger("ice.ai")

# A tool function: (domain args..., runtime) -> awaitable structured result.
ToolFn = TypeVar("ToolFn", bound=Callable[..., Awaitable[Any]])


def _error_result(kind: str, detail: str) -> dict[str, str]:
    return {"error": kind, "detail": detail}


def actor_from(runtime: Any) -> ActorContext:
    """Extract the immutable authenticated identity injected at invocation."""
    return cast(ActorContext, runtime.context)


def current_db() -> AsyncSession:
    """The request-scoped session bound by the harness (never tool-owned)."""
    return current_session()


def _json_default(value: Any) -> str:
    if isinstance(value, (Decimal, uuid.UUID, date, datetime)):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def bound_items(
    items: list[dict[str, Any]],
    *,
    total_count: int,
    limit: int,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Bound a list tool result by row count AND character budget.

    Never splits a JSON value: whole items are kept until the budget is
    reached, then the rest is dropped and `truncated` is set. The output is
    always valid structured JSON with explicit counts (LLM-friendly and
    testable).
    """
    budget = max_chars if max_chars is not None else settings.ICE_AI_MAX_TOOL_RESULT_CHARS
    kept: list[dict[str, Any]] = []
    used = 0
    truncated = False
    for item in items[:limit]:
        serialized = json.dumps(item, ensure_ascii=False, default=_json_default)
        if kept and used + len(serialized) > budget:
            truncated = True
            break
        kept.append(item)
        used += len(serialized)
    if len(items) > limit:
        truncated = True
    return {
        "items": kept,
        "total_count": total_count,
        "returned_count": len(kept),
        "truncated": truncated,
    }


def _raise_as_tool_error(exc: HTTPException) -> None:
    if exc.status_code == 404:
        raise ToolNotFound(str(exc.detail)) from exc
    if exc.status_code == 403:
        raise ToolForbidden(str(exc.detail)) from exc
    raise ToolError(str(exc.detail)) from exc


async def load_user(db: AsyncSession, actor: ActorContext) -> User:
    """Re-load the authenticated user deterministically from the actor facts."""
    user = await db.get(User, actor.user_id)
    if user is None or not user.is_active:
        raise ToolForbidden("The authenticated user is not active.")
    return user


def require_role(actor: ActorContext, *allowed: UserRole) -> None:
    """Hard role gate — mirrors the REST `require_role` dependency."""
    if actor.role not in allowed:
        raise ToolForbidden(
            f"Role '{actor.role.value}' is not permitted to perform this action"
        )


def assert_not_client_role(actor: ActorContext) -> None:
    """Internal management surfaces are off-limits to clients (M6 parity)."""
    if actor.role == UserRole.CLIENT:
        raise ToolForbidden("Role 'client' is not permitted to view this data")


async def get_project_visible(
    db: AsyncSession, user: User, project_id: uuid.UUID
) -> Project:
    """Resolve a project exactly like the REST read routes: existence check,
    ARCHIVED -> 404 for non-admin/procurement, then assignment visibility."""
    try:
        project = await get_project_or_404(db, project_id)
        if project.status == ProjectStatus.ARCHIVED and not can_access_archived(user):
            raise ToolNotFound("Project not found")
        await assert_can_view_project(db, user, project)
    except HTTPException as exc:  # noqa: PERF203
        _raise_as_tool_error(exc)
    return project


async def get_project_any(db: AsyncSession, project_id: uuid.UUID) -> Project:
    """Existence-only resolution for admin/procurement-scoped tools."""
    try:
        project = await get_project_or_404(db, project_id)
    except HTTPException as exc:  # noqa: PERF203
        _raise_as_tool_error(exc)
    return project


async def list_visible_projects(db: AsyncSession, user: User, include_archived: bool) -> list[Project]:
    """Role-scoped project listing — reuses the canonical route query."""
    from app.api.v1.projects import _select_projects

    return await _select_projects(db, user, include_archived)


def compact_project(dump: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    """Whitelist-project fields for LLM context (role-scoped by construction:
    the serializer already dropped budget/health/lifecycle fields for
    supervisor/client roles, so absent keys stay absent)."""
    base = (
        "id",
        "project_code",
        "name",
        "status",
        "percent_complete",
        "start_date",
        "target_end_date",
        "budget_total",
        "budget_spent",
    )
    extra = ("site_address", "client_name", "completed_at") if detail else ()
    return {key: dump[key] for key in base + extra if key in dump}


def safe_tool(func: ToolFn) -> ToolFn:
    """Convert any tool exception into a safe, model-readable error dict.

    Keeps controlled denials ('not_permitted'/'not_found') and swallows
    unexpected exceptions into a generic 'internal' error so internal details
    never reach the model (ToolErrorMiddleware is an AI-4 milestone).
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except ToolForbidden as exc:
            return _error_result("not_permitted", str(exc))
        except ToolNotFound as exc:
            return _error_result("not_found", str(exc))
        except HTTPException as exc:  # noqa: PERF203
            _raise_as_tool_error(exc)
        except ToolError as exc:
            return _error_result("error", str(exc))
        except Exception:
            logger.exception("ICE Copilot tool failed: %s", getattr(func, "__name__", "tool"))
            return _error_result("internal", "The tool failed unexpectedly. Please try again.")

    return cast(ToolFn, wrapper)
