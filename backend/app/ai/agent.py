"""
ICE Copilot harness (AI-1): provider-agnostic model factory + agent orchestrator.

The rest of the AI module depends on the generic LangChain chat-model
interface, never on OpenAI-specific classes. Provider/model are chosen from
settings (ICE_AI_PROVIDER / ICE_AI_MODEL). Fallback/retry/PII/limit middleware
is an AI-4 concern and is deliberately absent here. No memory/checkpointing
(AI-2).

`stream_assistant` is the orchestrator: it runs the role-filtered
`create_agent` harness and translates LangChain's streaming events into OUR
stable ICE SSE contract (assistant_start / assistant_token / tool_started /
tool_finished / assistant_complete / error), so the frontend never depends on
LangChain/LangGraph event names.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Sequence

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context import ActorContext, session_scope
from app.ai.logging import (
    log_event,
    message_type_summary,
    sanitize_query,
    sanitize_tool_args,
    summarize_tool_result,
)
from app.ai.prompts import build_system_prompt
from app.ai.security import tools_for_role
from app.ai.tools import TOOL_BY_NAME
from app.core.config import settings
from app.models.user import UserRole

logger = logging.getLogger("ice.ai")

# Central mapping: internal tool name -> safe human-readable display label.
# The public SSE events and the capabilities endpoint use these labels; the
# raw tool names and their arguments are never exposed to the browser.
TOOL_LABELS: dict[str, str] = {
    "list_projects": "Projects",
    "get_project": "Project detail",
    "get_project_health": "Project health",
    "get_project_budget": "Project budget",
    "get_project_inventory": "Project inventory",
    "get_purchase_orders": "Purchase orders",
    "get_my_notifications": "Notifications",
}


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, name)


class AssistantNotConfigured(RuntimeError):
    """Raised when the Copilot is disabled or provider configuration is missing."""


# OpenRouter is OpenAI-compatible, so it is served through ChatOpenAI with a
# base_url (its own SDK is avoided on purpose: it would force pydantic>=2.11,
# conflicting with the project's pinned pydantic 2.9.2).
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_PROVIDER_KEY_SETTING: dict[str, str] = {
    "openai": "ICE_AI_OPENAI_API_KEY",
    "anthropic": "ICE_AI_ANTHROPIC_API_KEY",
    "groq": "ICE_AI_GROQ_API_KEY",
    "openrouter": "ICE_AI_OPENROUTER_API_KEY",
}


def _provider_api_key(provider: str) -> str:
    """Resolve the API key for a provider: provider-specific setting first,
    generic ICE_AI_API_KEY as the fallback."""
    specific = getattr(settings, _PROVIDER_KEY_SETTING.get(provider, ""), None)
    return (specific or settings.ICE_AI_API_KEY).strip()


def build_model() -> Any:
    """Create the configured chat model (provider-swappable).

    Provider/model come from settings (ICE_AI_PROVIDER / ICE_AI_MODEL) and the
    model is built through LangChain's init_chat_model abstraction, so changing
    provider only requires env config — no code or tool changes. Construction
    performs no network calls; a missing key or disabled flag fails cleanly.
    """
    if not settings.ICE_AI_ENABLED:
        raise AssistantNotConfigured("The ICE Copilot is disabled (ICE_AI_ENABLED=false).")
    provider = (settings.ICE_AI_PROVIDER or "").strip().lower()
    if not provider:
        raise AssistantNotConfigured("ICE_AI_PROVIDER is not configured.")
    api_key = _provider_api_key(provider)
    if not api_key:
        raise AssistantNotConfigured(
            f"No API key configured for provider '{provider}' "
            "(set ICE_AI_{PROVIDER}_API_KEY or ICE_AI_API_KEY)."
        )
    if provider == "openrouter":
        # OpenAI-compatible path (no dedicated SDK needed).
        base_url = settings.ICE_AI_BASE_URL or DEFAULT_OPENROUTER_BASE_URL
        return ChatOpenAI(
            model=settings.ICE_AI_MODEL,
            temperature=settings.ICE_AI_TEMPERATURE,
            api_key=SecretStr(api_key),
            base_url=base_url,
        )
    model_name = f"{provider}:{settings.ICE_AI_MODEL}"
    kwargs: dict[str, Any] = {"temperature": settings.ICE_AI_TEMPERATURE, "api_key": api_key}
    if provider == "openai" and settings.ICE_AI_BASE_URL:
        kwargs["base_url"] = settings.ICE_AI_BASE_URL
    return init_chat_model(model_name, **kwargs)


def tools_for_role_toolset(role: UserRole) -> list[Any]:
    """The tool objects this role's agent is given (defense in depth — each
    tool re-authorizes internally regardless of this filter)."""
    return [TOOL_BY_NAME[name] for name in sorted(tools_for_role(role))]


def build_agent(role: UserRole, model: Any = None) -> Any:
    """Assemble a create_agent harness for a role with its allowed tool set.

    `context_schema=ActorContext` is the PUBLIC LangChain v1 context API: the
    authenticated actor is passed to invocation via the `context=` kwarg and
    flows into `ToolRuntime.context`. Identity never appears in model-visible
    tool arguments (the `runtime` param is auto-hidden) and AgentState is not
    the auth source.
    """
    selected_model = model if model is not None else build_model()
    return create_agent(
        model=selected_model,
        tools=tools_for_role_toolset(role),
        system_prompt=build_system_prompt(),
        context_schema=ActorContext,
    )


async def run_agent(agent: Any, messages: Sequence[Any], actor: ActorContext, db: AsyncSession) -> Any:
    """Run the agent (non-streaming) with the session bound for the run.

    Tools receive the DB session through the request-scoped context variable
    and never open/commit their own transactions. The authenticated actor is
    passed through the public `context=` runtime-context API.
    """
    request_id = uuid.uuid4().hex
    started_at = time.perf_counter()
    run_fields: dict[str, Any] = {
        "actor_role": actor.role.value,
        "provider": settings.ICE_AI_PROVIDER,
        "model": settings.ICE_AI_MODEL,
        "message_chars": sum(len(str(getattr(m, "content", "") or "")) for m in messages),
    }
    if settings.ICE_AI_DEBUG:
        run_fields["query"] = sanitize_query(
            " ".join(str(getattr(m, "content", "") or "") for m in messages)
        )
        run_fields["available_tools"] = sorted(tools_for_role(actor.role))
    log_event(request_id, "assistant.run.started", **run_fields)
    try:
        async with session_scope(db):
            result = await agent.ainvoke({"messages": list(messages)}, context=actor)
    except Exception:
        log_event(
            request_id,
            "assistant.run.failed",
            safe_error_code="assistant_error",
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        raise
    log_event(
        request_id,
        "assistant.run.completed",
        duration_ms=int((time.perf_counter() - started_at) * 1000),
        result="success",
    )
    return result


# --- ICE SSE event adapter ----------------------------------------------------


def _tool_result_data(content: Any) -> dict[str, Any] | None:
    """Best-effort parse of a ToolMessage's JSON content (our tools return
    structured dicts). Any non-JSON content is treated as a plain result."""
    if not content:
        return None
    if isinstance(content, dict):
        return content
    try:
        data = json.loads(str(content))
        return data if isinstance(data, dict) else None
    except (TypeError, ValueError):
        return None


def _is_error_result(content: Any) -> bool:
    data = _tool_result_data(content)
    return bool(data and data.get("error"))


def _is_denial_result(content: Any) -> bool:
    data = _tool_result_data(content)
    return bool(data and data.get("error") == "not_permitted")


def _capture_usage(usage: Any, metrics: dict[str, int]) -> None:
    """Defensive usage capture — missing provider metadata never breaks a run."""
    if not isinstance(usage, dict):
        return
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            metrics[key] += int(value)


def _event(event: str, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return (event, data)


async def stream_assistant(
    db: AsyncSession,
    actor: ActorContext,
    message: str,
    model: Any = None,
    agent: Any = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Run one stateless assistant turn, yielding (event, payload) tuples.

    Events: assistant_start, assistant_token, tool_started, tool_finished,
    assistant_complete, error — see the AI-1 plan §13. Only safe data is
    emitted: no tool arguments, no chain-of-thought, no secrets, no raw
    exceptions.
    """
    request_id = uuid.uuid4().hex
    started_at = time.perf_counter()
    metrics = {
        "model_calls": 0,
        "tool_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "tool_result_chars": 0,
        "auth_denials": 0,
    }
    final_parts: list[str] = []
    debug = settings.ICE_AI_DEBUG

    # Execution-trace state (observable loop only — never reasoning/CoT).
    trace: list[str] = ["SystemMessage", "HumanMessage"]
    tool_counts: dict[str, int] = {}
    tool_start_times: dict[str, float] = {}
    model_turn_active = False
    model_turn_start = 0.0
    model_turn_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    token_event_count = 0

    yield _event("assistant_start", {"request_id": request_id, "read_only": True})
    run_fields: dict[str, Any] = {
        "actor_role": actor.role.value,
        "provider": settings.ICE_AI_PROVIDER,
        "model": settings.ICE_AI_MODEL,
        "tool_count": len(tools_for_role_toolset(actor.role)),
        "message_chars": len(message),
    }
    if debug:
        run_fields["query"] = sanitize_query(message)
        run_fields["available_tools"] = sorted(tools_for_role(actor.role))
    log_event(request_id, "assistant.run.started", **run_fields)

    try:
        selected_agent = agent if agent is not None else build_agent(actor.role, model=model)
        async with session_scope(db):
            async for mode, payload in selected_agent.astream(
                {"messages": [("user", message)]},
                context=actor,
                stream_mode=["messages", "updates"],
            ):
                if mode == "updates":
                    for node, update in payload.items():
                        if node == "model":
                            metrics["model_calls"] += 1
                            requested: list[dict[str, Any]] = []
                            for msg in update.get("messages", []):
                                for tool_call in getattr(msg, "tool_calls", None) or []:
                                    requested.append(tool_call)
                                    yield _event(
                                        "tool_started",
                                        {"tool": tool_label(str(tool_call.get("name", "")))},
                                    )
                            latency_ms = (
                                (time.perf_counter() - model_turn_start) * 1000
                                if model_turn_active
                                else None
                            )
                            log_event(
                                request_id,
                                "assistant.model.completed",
                                model_call_number=metrics["model_calls"],
                                latency_ms=round(latency_ms) if latency_ms else None,
                                tool_calls_requested=len(requested),
                                input_tokens=model_turn_usage["input_tokens"],
                                output_tokens=model_turn_usage["output_tokens"],
                                total_tokens=model_turn_usage["total_tokens"],
                            )
                            now = time.perf_counter()
                            for tool_call in requested:
                                name = str(tool_call.get("name", ""))
                                tool_start_times[name] = now
                                tool_fields: dict[str, Any] = {
                                    "tool": name,
                                    "tool_call_number": tool_counts.get(name, 0) + 1,
                                }
                                if debug:
                                    tool_fields["args"] = sanitize_tool_args(
                                        tool_call.get("args")
                                    )
                                log_event(request_id, "assistant.tool.started", **tool_fields)
                            for msg in update.get("messages", []):
                                trace.append(message_type_summary(msg))
                            model_turn_active = False
                        elif node == "tools":
                            for msg in update.get("messages", []):
                                metrics["tool_calls"] += 1
                                content = getattr(msg, "content", None)
                                text = str(content or "")
                                metrics["tool_result_chars"] += len(text)
                                tool_name = str(getattr(msg, "name", ""))
                                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                                if _is_denial_result(content):
                                    metrics["auth_denials"] += 1
                                    log_event(
                                        request_id,
                                        "assistant.authorization.denied",
                                        tool=tool_name,
                                        actor_role=actor.role.value,
                                        reason_code="not_permitted",
                                    )
                                result_data = _tool_result_data(content)
                                error_kind = result_data.get("error") if result_data else None
                                finished: dict[str, Any] = {
                                    "tool": tool_label(tool_name),
                                    "ok": not _is_error_result(content),
                                }
                                if error_kind:
                                    finished["error"] = str(error_kind)
                                yield _event("tool_finished", finished)
                                start = tool_start_times.pop(tool_name, None)
                                duration_ms = (
                                    (time.perf_counter() - start) * 1000 if start else None
                                )
                                tool_done_fields: dict[str, Any] = {
                                    "tool": tool_name,
                                    "ok": not _is_error_result(content),
                                    "duration_ms": round(duration_ms) if duration_ms else None,
                                    "result_chars": len(text),
                                }
                                if result_data:
                                    tool_done_fields["returned_count"] = result_data.get(
                                        "returned_count"
                                    )
                                    tool_done_fields["truncated"] = result_data.get("truncated")
                                if debug:
                                    tool_done_fields["result_summary"] = summarize_tool_result(
                                        tool_name, result_data
                                    )
                                log_event(request_id, "assistant.tool.completed", **tool_done_fields)
                                trace.append(message_type_summary(msg))
                else:  # "messages"
                    chunk, meta = payload
                    if meta.get("langgraph_node") == "model":
                        content = getattr(chunk, "content", None)
                        if isinstance(content, str) and content and not getattr(
                            chunk, "tool_calls", None
                        ):
                            final_parts.append(content)
                            token_event_count += 1
                            yield _event("assistant_token", {"text": content})
                        _capture_usage(getattr(chunk, "usage_metadata", None), metrics)
                        if not model_turn_active:
                            model_turn_active = True
                            model_turn_start = time.perf_counter()
                            model_turn_usage = {
                                "input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": 0,
                            }
                            model_fields: dict[str, Any] = {
                                "model_call_number": metrics["model_calls"] + 1,
                                "provider": settings.ICE_AI_PROVIDER,
                                "model": settings.ICE_AI_MODEL,
                                "message_count": len(trace),
                            }
                            if debug:
                                model_fields["available_tool_count"] = len(
                                    tools_for_role_toolset(actor.role)
                                )
                                model_fields["messages"] = trace.copy()
                            log_event(request_id, "assistant.model.started", **model_fields)
                        _capture_usage(getattr(chunk, "usage_metadata", None), model_turn_usage)

        final_text = "".join(final_parts)
        log_event(
            request_id,
            "assistant.stream.completed",
            token_event_count=token_event_count,
            response_chars=len(final_text),
        )
        if debug:
            log_event(request_id, "assistant.run.tool_counts", **tool_counts)
        log_event(
            request_id,
            "assistant.run.completed",
            model_calls=metrics["model_calls"],
            tool_calls=metrics["tool_calls"],
            authorization_denials=metrics["auth_denials"],
            input_tokens=metrics["input_tokens"],
            output_tokens=metrics["output_tokens"],
            total_tokens=metrics["total_tokens"],
            tool_result_chars=metrics["tool_result_chars"],
            response_chars=len(final_text),
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            result="success",
        )
        yield _event(
            "assistant_complete",
            {
                "request_id": request_id,
                "usage": {
                    "model_calls": metrics["model_calls"],
                    "tool_calls": metrics["tool_calls"],
                    "input_tokens": metrics["input_tokens"],
                    "output_tokens": metrics["output_tokens"],
                    "total_tokens": metrics["total_tokens"],
                },
                "took_ms": int((time.perf_counter() - started_at) * 1000),
            },
        )
    except Exception:
        logger.exception("ICE Copilot run failed (request %s)", request_id)
        log_event(
            request_id,
            "assistant.run.failed",
            safe_error_code="assistant_error",
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        yield _event(
            "error",
            {
                "code": "assistant_error",
                "message": "The assistant could not complete this request.",
            },
        )
