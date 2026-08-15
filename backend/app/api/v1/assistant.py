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
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ai.agent import (
    build_model,
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
    controlled — none of them are accepted from the client."""

    message: str = Field(min_length=1, max_length=4000, description="The user's message.")


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

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event, data in stream_assistant(db, actor, message, model=model):
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
        "read_only": True,
        "tools": tools,
        "memory_enabled": False,
        "web_search_enabled": False,
        "mutations_enabled": False,
    }
