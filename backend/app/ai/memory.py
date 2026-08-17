"""
ICE Copilot conversation memory (W7.1).

InMemorySaver is the course-taught checkpointer. Lifecycle:

- ONE process-level singleton (`_checkpointer`) — never instantiated per
  request (a fresh saver per request would defeat memory).
- Threads are keyed by a SERVER-namespaced id `{user_id}::{external_thread_id}`.
  A raw client thread id (e.g. "abc") can therefore never collide across users:
  User A and User B sending "abc" resolve to different internal conversations.
- LIMITATION (documented): InMemorySaver is process-local — memory disappears on
  restart and is NOT consistently available across multiple backend workers.
  Persistent checkpoint storage (Postgres/Redis) is explicitly out of scope for
  W7.1.

Memory is MESSAGE/CONVERSATION state only. Identity/authorization is NEVER
stored here — every request constructs a fresh ActorContext from the
authenticated FastAPI user and injects it via the public `context=` API.
"""
from __future__ import annotations

import uuid

from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import settings

_checkpointer = InMemorySaver()

# Memory modes (see settings.ICE_AI_MEMORY_MODE).
MEMORY_MODE_NONE = "none"
MEMORY_MODE_SAVER = "saver"
MEMORY_MODE_SUMMARIZE = "summarize"
MEMORY_MODE_CONTEXT_EDIT = "context_edit"
MEMORY_MODES = frozenset(
    {MEMORY_MODE_NONE, MEMORY_MODE_SAVER, MEMORY_MODE_SUMMARIZE, MEMORY_MODE_CONTEXT_EDIT}
)


def get_checkpointer() -> InMemorySaver:
    """The process-level InMemorySaver singleton."""
    return _checkpointer


def memory_mode() -> str:
    mode = (settings.ICE_AI_MEMORY_MODE or MEMORY_MODE_NONE).strip().lower()
    return mode if mode in MEMORY_MODES else MEMORY_MODE_NONE


def memory_enabled() -> bool:
    return memory_mode() != MEMORY_MODE_NONE


def thread_key(user_id: uuid.UUID, external_thread_id: str) -> str:
    """Server-namespaced internal checkpoint key — never exposed to the model."""
    return f"{user_id}::{external_thread_id}"


def run_config(user_id: uuid.UUID, thread_id: str | None) -> dict:
    """Invocation config carrying the (namespaced) thread id.

    When memory is enabled and no thread_id is supplied, an ephemeral random
    thread is used so stateless single-turn calls keep working (each request
    becomes its own throwaway conversation).
    """
    if not memory_enabled():
        return {}
    external = thread_id or uuid.uuid4().hex
    return {"configurable": {"thread_id": thread_key(user_id, external)}}
