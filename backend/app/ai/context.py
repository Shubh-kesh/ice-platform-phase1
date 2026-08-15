"""
Authenticated invocation context for the ICE Copilot.

The authoritative identity is the FastAPI-authenticated `User` (deps.py
`get_current_user`). `ActorContext` is a frozen, minimal projection of that
identity that is injected into the agent via `ToolRuntime.context` by the
harness — the model has no way to provide or modify it, and its fields are
never part of any tool's model-visible argument schema.

A request-scoped database session is carried in a context variable so tool
signatures stay free of DB plumbing (and of any model-visible argument).
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


class ActorContext(BaseModel):
    """Immutable authenticated identity facts available to ICE tools.

    Deliberately minimal: `user_id` + `role`. No email, no project-access
    list, no name — the tool layer recomputes authorization deterministically
    from these facts via the existing `project_access` helpers on every call.
    """

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    role: UserRole

    @classmethod
    def from_user(cls, user: User) -> "ActorContext":
        return cls(user_id=user.id, role=user.role)


_session_var: ContextVar[AsyncSession | None] = ContextVar(
    "ice_ai_db_session", default=None
)


@asynccontextmanager
async def session_scope(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Bind a database session for the duration of an agent run (or tool call).

    Mirrors how `get_db` provides a per-request session: the harness sets the
    session before invoking the agent and restores the previous value after,
    so the tools always operate on the authenticated request's session and
    never create or commit their own transactions.
    """
    token = _session_var.set(session)
    try:
        yield session
    finally:
        _session_var.reset(token)


def current_session() -> AsyncSession:
    """Return the session bound for the current invocation."""
    session = _session_var.get()
    if session is None:
        raise RuntimeError("No ICE Copilot database session is bound to this invocation.")
    return session
