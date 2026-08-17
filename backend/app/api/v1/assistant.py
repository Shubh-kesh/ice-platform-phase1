"""
ICE Copilot HTTP surface (AI-1.2).

POST /assistant/chat        — one stateless, authenticated, role-filtered
                              assistant turn, streamed as SSE events.
GET  /assistant/capabilities— safe, role-scoped capability metadata for the UI.

Authentication is mandatory (Bearer JWT via get_current_user); no public AI
endpoint. HTTP-level failures (401 auth, 429 rate limit, 503 disabled) happen
BEFORE streaming starts; after streaming begins, failures become a safe `error`
SSE event.
"""
import json
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.ai import memory as ai_memory
from app.ai.agent import (
    build_model,
    resume_assistant,
    stream_assistant,
    tool_label,
    tools_for_role_toolset,
)
from app.ai.context import ActorContext
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import ASSISTANT_RATE_LIMIT, limiter
from app.models.user import User

router = APIRouter(prefix="/assistant", tags=["assistant"])

_CHAT_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # tell proxies not to buffer the SSE stream
}


class AssistantChatRequest(BaseModel):
    """A single user turn. Identity, role, tools and model are SERVER
    controlled — none of them are accepted from the client.

    `thread_id` is a CLIENT-generated external conversation id (a UUID). The
    server namespaces it by the authenticated actor (`{user_id}::{thread_id}`),
    so the same external id can never collide across users and cross-user
    access is structurally impossible.
    """

    message: str = Field(min_length=1, max_length=4000, description="The user's message.")
    thread_id: str | None = Field(
        default=None,
        min_length=36,
        max_length=36,
        description="Client-generated conversation id (UUID) to continue.",
    )

    @field_validator("thread_id")
    @classmethod
    def _thread_id_must_be_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError("thread_id must be a UUID") from exc
        return value


class AssistantResumeRequest(BaseModel):
    """A human decision on an interrupted mutating-tool proposal.

    Only what the decision requires: the thread id, the decision, and (for
    edit/reject/respond) the edited action or message. Identity, role, provider,
    model and the internal checkpoint namespace are SERVER controlled — never
    accepted from the client.
    """

    thread_id: str = Field(description="Client conversation id (UUID) of the thread with the pending approval.")
    decision: str = Field(description="approve | edit | reject | respond")
    edited_action: dict[str, Any] | None = Field(
        default=None,
        description="For 'edit': the revised tool call ({name, args}) the human approved.",
    )
    message: str | None = Field(
        default=None,
        max_length=1000,
        description="For 'reject'/'respond': the human's message (reject reason / answer).",
    )

    @field_validator("thread_id")
    @classmethod
    def _resume_thread_id_must_be_uuid(cls, value: str) -> str:
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError("thread_id must be a UUID") from exc
        return value


def _sse_frame(event: str, data: dict[str, Any]) -> str:
    """Encode one event as an SSE frame: `event: <name>` + `data: <json>`."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def _ensure_enabled() -> None:
    if not settings.ICE_AI_ENABLED or not settings.ICE_AI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="The ICE Copilot is not enabled.",
        )


@router.post("/chat")
@limiter.limit(ASSISTANT_RATE_LIMIT)
async def assistant_chat(
    request: Request,
    payload: AssistantChatRequest,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Run one authenticated assistant turn and stream the result as SSE."""
    _ensure_enabled()
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message must not be empty")
    actor = ActorContext.from_user(user)
    model = build_model()  # construction only — no network; fails -> 503 via _ensure_enabled
    thread_id = payload.thread_id

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event, data in stream_assistant(
                db, actor, message, model=model, thread_id=thread_id
            ):
                yield _sse_frame(event, data)
        except Exception:  # backstop after streaming has started
            yield _sse_frame(
                "error",
                {
                    "code": "assistant_error",
                    "message": "The assistant could not complete this request.",
                },
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers=_CHAT_HEADERS,
    )


@router.post("/resume")
@limiter.limit(ASSISTANT_RATE_LIMIT)
async def assistant_resume(
    request: Request,
    payload: AssistantResumeRequest,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Resume an interrupted mutating-tool proposal with the human's decision.

    The thread resolves to the authenticated user's namespace, so User B can
    never resume User A's pending approval even with the same external
    thread_id. Streams the continuation (tool execution + final answer) as SSE.
    """
    _ensure_enabled()
    actor = ActorContext.from_user(user)
    model = build_model()
    thread_id = payload.thread_id
    decision = payload.decision.strip().lower()
    if decision not in ("approve", "edit", "reject", "respond"):
        raise HTTPException(
            status_code=422,
            detail="decision must be one of: approve, edit, reject, respond",
        )

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event, data in resume_assistant(
                db,
                actor,
                thread_id,
                decision,
                model=model,
                edited_action=payload.edited_action,
                message=payload.message,
            ):
                yield _sse_frame(event, data)
        except Exception:  # backstop after streaming has started
            yield _sse_frame(
                "error",
                {
                    "code": "assistant_error",
                    "message": "The assistant could not complete this request.",
                },
            )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers=_CHAT_HEADERS,
    )


@router.get("/capabilities")
async def assistant_capabilities(
    user: User = Depends(get_current_user),
):
    """Safe, role-scoped capability metadata for the assistant UI.

    Deliberately excludes the system prompt, raw tool schemas, provider keys,
    DB details and any internal authorization implementation.
    """
    tools = [
        {"name": name, "label": tool_label(name)}
        for name in sorted(t.name for t in tools_for_role_toolset(user.role))
    ]
    return {
        "enabled": bool(settings.ICE_AI_ENABLED and settings.ICE_AI_API_KEY),
        "read_only": not settings.ICE_AI_MUTATIONS_ENABLED,
        "tools": tools,
        # W7.1: conversation memory is PROCESS-LOCAL (InMemorySaver) — it does
        # not survive a restart and is not shared across backend workers.
        "memory_enabled": ai_memory.memory_enabled(),
        "memory_mode": ai_memory.memory_mode(),
        # W7.2: external search — flag only; never the key or provider internals.
        "web_search_enabled": settings.ICE_AI_WEB_SEARCH_ENABLED,
        # W7.4: controlled mutations behind HITL (each still requires a human
        # decision; default off -> read-only product preserved).
        "mutations_enabled": settings.ICE_AI_MUTATIONS_ENABLED,
    }
