"""
ICE Copilot harness: provider-agnostic model factory + agent orchestrator.

The rest of the AI module depends on the generic LangChain chat-model
interface, never on OpenAI-specific classes. Provider/model are chosen from
settings (ICE_AI_PROVIDER / ICE_AI_MODEL). The full W7.3 middleware stack is
built by `app/ai/middleware.py` in one explicit order.

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
from langgraph.types import Command
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import memory as ai_memory
from app.ai import middleware as ai_middleware
from app.ai.context import ActorContext, session_scope
from app.ai.logging import (
    log_event,
    message_type_summary,
    sanitize_query,
    sanitize_tool_args,
    summarize_tool_result,
)
from app.ai.prompts import build_system_prompt
from app.ai.security import TOOL_WEB_SEARCH, tools_for_role
from app.ai import security as ai_security
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
    "get_purchase_order_deliveries": "Purchase order deliveries",
    "get_billing_milestones": "Billing milestones",
    "get_invoices": "Invoices",
    "get_project_tasks": "Project tasks",
    "get_daily_site_logs": "Daily site logs",
    "get_job_costs": "Job costs",
    "get_my_notifications": "Notifications",
    "web_search": "Web search",
    # W7.4 mutating tools (HITL-guarded).
    "create_task": "Create task",
    "create_daily_site_log": "Create daily site log",
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


def _build_provider_model(provider: str, model_name: str) -> Any:
    """Construct a chat model for an arbitrary provider/model (fallback,
    selector). No network at construction; keys resolved server-side."""
    provider = (provider or "").strip().lower()
    api_key = _provider_api_key(provider)
    if not api_key:
        raise AssistantNotConfigured(
            f"No API key configured for provider '{provider}' "
            "(set ICE_AI_{PROVIDER}_API_KEY or ICE_AI_API_KEY)."
        )
    if provider == "openrouter":
        base_url = settings.ICE_AI_BASE_URL or DEFAULT_OPENROUTER_BASE_URL
        return ChatOpenAI(
            model=model_name,
            temperature=settings.ICE_AI_TEMPERATURE,
            api_key=SecretStr(api_key),
            base_url=base_url,
        )
    kwargs: dict[str, Any] = {"temperature": settings.ICE_AI_TEMPERATURE, "api_key": api_key}
    if provider == "openai" and settings.ICE_AI_BASE_URL:
        kwargs["base_url"] = settings.ICE_AI_BASE_URL
    return init_chat_model(f"{provider}:{model_name}", **kwargs)


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
    return _build_provider_model(provider, settings.ICE_AI_MODEL)


# Decisions allowed for each mutating tool. create_task is unambiguous enough
# for approve/edit/reject (+ respond lets the human answer on behalf of the
# tool); create_daily_site_log is append-only so respond is NOT allowed (the
# human should reject rather than fabricate a field record).
HITL_ALLOWED_DECISIONS: dict[str, list[Any]] = {
    "create_task": ["approve", "edit", "reject", "respond"],
    "create_daily_site_log": ["approve", "edit", "reject"],
}


def hitl_middleware() -> Any:
    """HumanInTheLoopMiddleware configured for the W7.4 mutating tools.

    Interrupts ONLY the mutating tools; every read-only tool auto-approves and
    continues normally. The `description` (str + callable) builds a
    reasoning-free, safe summary for the approval card.
    """
    from langchain.agents.middleware import HumanInTheLoopMiddleware

    def _summary(tool_call: Any, state: Any, runtime: Any) -> str:
        args = tool_call.get("args", {})
        tool_name = str(tool_call.get("name", ""))
        if tool_name == "create_task":
            return (
                f"Create task '{args.get('name', '')}' "
                f"({args.get('start_date', '?')} to {args.get('end_date', '?')})"
            )
        if tool_name == "create_daily_site_log":
            return (
                f"Create daily site log for {args.get('log_date', '?')}: "
                f"{str(args.get('work_summary', ''))[:160]}"
            )
        return f"{tool_name} requires approval"

    return HumanInTheLoopMiddleware(
        interrupt_on={
            "create_task": {
                "allowed_decisions": HITL_ALLOWED_DECISIONS["create_task"],
                "description": _summary,
            },
            "create_daily_site_log": {
                "allowed_decisions": HITL_ALLOWED_DECISIONS["create_daily_site_log"],
                "description": _summary,
            },
        }
    )


def tools_for_role_toolset(role: UserRole) -> list[Any]:
    """The tool objects this role's agent is given (defense in depth — each
    tool re-authorizes internally regardless of this filter).

    `web_search` is only surfaced when external search is enabled (default
    off) and the W7.4 mutating tools only when mutations are enabled (default
    off), so a disabled feature is not even on the model's menu.
    """
    names = [
        name
        for name in sorted(tools_for_role(role))
        if (name != TOOL_WEB_SEARCH or settings.ICE_AI_WEB_SEARCH_ENABLED)
        and (name not in ai_security.MUTATING_TOOLS or settings.ICE_AI_MUTATIONS_ENABLED)
    ]
    return [TOOL_BY_NAME[name] for name in names]


def build_agent(
    role: UserRole,
    model: Any = None,
    memory_mode: str | None = None,
    summarization_model: Any = None,
) -> Any:
    """Assemble a create_agent harness for a role with its allowed tool set.

    `context_schema=ActorContext` is the PUBLIC LangChain v1 context API: the
    authenticated actor is passed to invocation via the `context=` kwarg and
    flows into `ToolRuntime.context`. Identity never appears in model-visible
    tool arguments (the `runtime` param is auto-hidden) and AgentState is not
    the auth source.

    W7.1 memory: `memory_mode` selects the checkpointer + middleware combo
    (`none` | `saver` | `summarize` | `context_edit`). The checkpointer is the
    process-level InMemorySaver singleton; thread ids are server-namespaced in
    the invocation config. Memory is message state only — never authorization.
    """
    mem_mode = memory_mode if memory_mode in ai_memory.MEMORY_MODES else ai_memory.memory_mode()
    # W7.4: mutations require a user-namespaced thread (checkpointer) so HITL
    # interrupts can be resumed. Force the "saver" mode when mutations are on.
    if settings.ICE_AI_MUTATIONS_ENABLED and mem_mode == ai_memory.MEMORY_MODE_NONE:
        mem_mode = settings.ICE_AI_HITL_MEMORY_MODE
    selected_model = model if model is not None else build_model()
    checkpointer = (
        ai_memory.get_checkpointer() if mem_mode != ai_memory.MEMORY_MODE_NONE else None
    )

    # Fallback / selector models: server-side, only when configured. Never
    # exposed to the model or frontend.
    fallback_model: Any = None
    if settings.ICE_AI_FALLBACK_PROVIDER and settings.ICE_AI_FALLBACK_MODEL:
        try:
            fallback_model = _build_provider_model(
                settings.ICE_AI_FALLBACK_PROVIDER, settings.ICE_AI_FALLBACK_MODEL
            )
        except AssistantNotConfigured:
            fallback_model = None
    selector_model: Any = None
    if settings.ICE_AI_TOOL_SELECTOR_ENABLED:
        selector_model = (
            _build_provider_model(
                settings.ICE_AI_TOOL_SELECTOR_PROVIDER or settings.ICE_AI_PROVIDER,
                settings.ICE_AI_TOOL_SELECTOR_MODEL or settings.ICE_AI_MODEL,
            )
            if not model
            else model
        )
    sum_model = (
        summarization_model
        if summarization_model is not None
        else (build_model() if mem_mode == ai_memory.MEMORY_MODE_SUMMARIZE else None)
    )

    middleware = ai_middleware.build_middleware(
        memory_mode=mem_mode,
        primary_model=selected_model,
        summarization_model=sum_model,
        fallback_model=fallback_model,
        selector_model=selector_model,
    )
    if settings.ICE_AI_TODO_ENABLED:
        from langchain.agents.middleware import TodoListMiddleware

        middleware.append(TodoListMiddleware())
    if settings.ICE_AI_MUTATIONS_ENABLED:
        middleware.append(hitl_middleware())

    tools = tools_for_role_toolset(role)
    return create_agent(
        model=selected_model,
        tools=tools,
        system_prompt=build_system_prompt(),
        context_schema=ActorContext,
        checkpointer=checkpointer,
        middleware=middleware,
    )


async def run_agent(
    agent: Any,
    messages: Sequence[Any],
    actor: ActorContext,
    db: AsyncSession,
    thread_id: str | None = None,
) -> Any:
    """Run the agent (non-streaming) with the session bound for the run.

    Tools receive the DB session through the request-scoped context variable
    and never open/commit their own transactions. The authenticated actor is
    passed through the public `context=` runtime-context API; the optional
    thread_id enables the namespaced conversation memory (W7.1).
    """
    request_id = uuid.uuid4().hex
    started_at = time.perf_counter()
    mem_mode = ai_memory.memory_mode()
    config = ai_memory.run_config(actor.user_id, thread_id)
    run_fields: dict[str, Any] = {
        "actor_role": actor.role.value,
        "provider": settings.ICE_AI_PROVIDER,
        "model": settings.ICE_AI_MODEL,
        "message_chars": sum(len(str(getattr(m, "content", "") or "")) for m in messages),
        "thread_id_safe": thread_id,
        "memory_mode": mem_mode,
    }
    if settings.ICE_AI_DEBUG:
        run_fields["query"] = sanitize_query(
            " ".join(str(getattr(m, "content", "") or "") for m in messages)
        )
        run_fields["available_tools"] = sorted(tools_for_role(actor.role))
    log_event(request_id, "assistant.run.started", **run_fields)
    try:
        async with session_scope(db):
            result = await agent.ainvoke(
                {"messages": list(messages)}, config=config, context=actor
            )
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


# --- W7.4 HITL interrupt helpers -------------------------------------------------


# Safe, model-visible editable fields per mutating tool (the ONLY fields the
# approval card lets a human edit; never identity/runtime fields).
HITL_EDITABLE_FIELDS: dict[str, dict[str, dict[str, str]]] = {
    "create_task": {
        "name": {"label": "Task name", "type": "text"},
        "start_date": {"label": "Start date", "type": "date"},
        "end_date": {"label": "End date", "type": "date"},
    },
    "create_daily_site_log": {
        "log_date": {"label": "Log date", "type": "date"},
        "work_summary": {"label": "Work summary", "type": "text"},
        "issues": {"label": "Issues", "type": "text"},
        "workers_present": {"label": "Workers present", "type": "number"},
        "weather": {"label": "Weather", "type": "text"},
    },
}


def _interrupt_value(state: Any) -> dict[str, Any] | None:
    """The HITLRequest payload from a pending checkpoint interrupt, as a dict."""
    for interrupt in getattr(state, "interrupts", None) or ():
        value = interrupt.value
        if isinstance(value, dict) and value.get("action_requests"):
            return value
    return None


def _approval_event(external_thread: str | None, interrupt_value: dict[str, Any]) -> dict[str, Any]:
    """Build the safe `approval_required` SSE payload.

    Emits ONLY safe data: tool label, a reasoning-free server-built summary,
    the whitelisted editable fields with their proposed values, and the allowed
    decisions. Never the internal checkpoint key, raw schemas, or full args.
    """
    action = interrupt_value["action_requests"][0]
    review = interrupt_value["review_configs"][0]
    name = str(action.get("name", ""))
    args = action.get("args") or {}
    editable: dict[str, dict[str, Any]] = {}
    for field, meta in HITL_EDITABLE_FIELDS.get(name, {}).items():
        if field in args:
            editable[field] = {**meta, "value": args[field]}
    return {
        "thread_id": external_thread,
        "action_id": str(uuid.uuid4().hex[:8]),
        "tool": tool_label(name),
        "summary": str(action.get("description", "")),
        "editable_fields": editable,
        "allowed_decisions": list(review.get("allowed_decisions") or []),
    }


async def stream_assistant(
    db: AsyncSession,
    actor: ActorContext,
    message: str,
    model: Any = None,
    agent: Any = None,
    thread_id: str | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Run one assistant turn, yielding (event, payload) tuples.

    Events: assistant_start, assistant_token, tool_started, tool_finished,
    assistant_complete, error — see the AI-1 plan §13. Only safe data is
    emitted: no tool arguments, no chain-of-thought, no secrets, no raw
    exceptions. W7.1: `thread_id` enables namespaced conversation memory;
    without it (and with memory on) an ephemeral thread is used per request.
    """
    request_id = uuid.uuid4().hex
    started_at = time.perf_counter()
    mem_mode = ai_memory.memory_mode()
    external_thread = (
        thread_id if thread_id else (uuid.uuid4().hex if ai_memory.memory_enabled() else None)
    )
    run_config = ai_memory.run_config(actor.user_id, thread_id)
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
    interrupted = False

    yield _event(
        "assistant_start",
        {
            "request_id": request_id,
            "read_only": not settings.ICE_AI_MUTATIONS_ENABLED,
            "thread_id": external_thread,
            "memory_mode": mem_mode,
        },
    )
    run_fields: dict[str, Any] = {
        "actor_role": actor.role.value,
        "provider": settings.ICE_AI_PROVIDER,
        "model": settings.ICE_AI_MODEL,
        "tool_count": len(tools_for_role_toolset(actor.role)),
        "message_chars": len(message),
        "thread_id_safe": external_thread,
        "memory_mode": mem_mode,
    }
    if debug:
        run_fields["query"] = sanitize_query(message)
        run_fields["available_tools"] = sorted(tools_for_role(actor.role))
    log_event(request_id, "assistant.run.started", **run_fields)

    try:
        selected_agent = (
            agent
            if agent is not None
            else build_agent(actor.role, model=model, memory_mode=mem_mode)
        )
        async with session_scope(db):
            async for mode, payload in selected_agent.astream(
                {"messages": [("user", message)]},
                config=run_config,
                context=actor,
                stream_mode=["messages", "updates"],
            ):
                if mode == "updates":
                    for node, update in payload.items():
                        if node == "__interrupt__":
                            # W7.4: HumanInTheLoop interrupted a mutating tool
                            # proposal. Stop streaming; the approval card is
                            # served from the checkpoint state below.
                            interrupted = True
                            break
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
                                if name == TOOL_WEB_SEARCH:
                                    tool_fields["external"] = True
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
                                if tool_name == TOOL_WEB_SEARCH:
                                    tool_done_fields["external"] = True
                                if result_data:
                                    tool_done_fields["returned_count"] = result_data.get(
                                        "returned_count"
                                    )
                                    tool_done_fields["truncated"] = result_data.get("truncated")
                                    if tool_name == TOOL_WEB_SEARCH:
                                        tool_done_fields["search_result_count"] = result_data.get(
                                            "returned_count"
                                        )
                                if debug:
                                    tool_done_fields["result_summary"] = summarize_tool_result(
                                        tool_name, result_data
                                    )
                                log_event(request_id, "assistant.tool.completed", **tool_done_fields)
                                trace.append(message_type_summary(msg))
                    if interrupted:
                        break
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

        if interrupted:
            # W7.4: the agent proposed a mutation and the HumanInTheLoop
            # middleware paused the run. No tool executed, so the database and
            # audit trail are untouched. Serve the safe approval card.
            state = await selected_agent.aget_state(run_config)
            interrupt_value = _interrupt_value(state)
            if interrupt_value is None:
                log_event(
                    request_id,
                    "assistant.hitl.interrupted",
                    thread_id_safe=external_thread,
                    pending="unknown",
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
                yield _event(
                    "error",
                    {
                        "code": "hitl_error",
                        "message": "The action needs approval but no approval record was found.",
                    },
                )
                return
            action_name = str(interrupt_value["action_requests"][0].get("name", ""))
            log_event(
                request_id,
                "assistant.hitl.interrupted",
                tool=action_name,
                thread_id_safe=external_thread,
                allowed_decisions=HITL_ALLOWED_DECISIONS.get(action_name, []),
                duration_ms=int((time.perf_counter() - started_at) * 1000),
            )
            log_event(
                request_id,
                "assistant.run.completed",
                result="pending_approval",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                thread_id_safe=external_thread,
                memory_mode=mem_mode,
            )
            yield _event("approval_required", _approval_event(external_thread, interrupt_value))
            return

        final_text = "".join(final_parts)
        # Best-effort stored-message count from the checkpointer (memory only).
        stored_message_count: int | None = None
        if run_config:
            try:
                state = await selected_agent.aget_state(run_config)
                stored_message_count = len(state.values.get("messages", []))
            except Exception:  # noqa: BLE001 - state inspection must never break a run
                stored_message_count = None
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
            thread_id_safe=external_thread,
            memory_mode=mem_mode,
            context_message_count=len(trace),
            stored_message_count=stored_message_count,
        )
        yield _event(
            "assistant_complete",
            {
                "request_id": request_id,
                "thread_id": external_thread,
                "memory_mode": mem_mode,
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


async def resume_assistant(
    db: AsyncSession,
    actor: ActorContext,
    thread_id: str,
    decision: str,
    model: Any = None,
    agent: Any = None,
    edited_action: dict[str, Any] | None = None,
    message: str | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Resume an interrupted mutating-tool proposal with the human's decision.

    The thread resolves to the AUTHENTICATED actor's namespace
    (`{user_id}::{thread_id}`), so another user can never resume a proposal
    they do not own. `decision` is one of approve / edit / reject / respond and
    is validated against the tool's allowed decisions BEFORE resume.

    Events: assistant_start, assistant_resumed, tool_started, tool_finished,
    action_completed, assistant_token, assistant_complete, error.
    """
    request_id = uuid.uuid4().hex
    started_at = time.perf_counter()
    mem_mode = ai_memory.memory_mode()
    run_config = ai_memory.run_config(actor.user_id, thread_id)
    metrics = {"model_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    final_parts: list[str] = []
    debug = settings.ICE_AI_DEBUG
    tool_start_times: dict[str, float] = {}
    model_turn_active = False
    model_turn_start = 0.0
    model_turn_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    mutation_tool: str | None = None
    mutation_ok: bool | None = None

    yield _event(
        "assistant_start",
        {
            "request_id": request_id,
            "read_only": not settings.ICE_AI_MUTATIONS_ENABLED,
            "thread_id": thread_id,
            "memory_mode": mem_mode,
        },
    )
    log_event(
        request_id,
        "assistant.resume.started",
        actor_role=actor.role.value,
        thread_id_safe=thread_id,
        decision=decision,
    )

    try:
        selected_agent = (
            agent
            if agent is not None
            else build_agent(actor.role, model=model, memory_mode=mem_mode)
        )
        # The pending interrupt must be validated BEFORE resuming: same actor
        # thread ownership by construction (namespaced key). A thread with no
        # pending interrupt (or a completed one) is rejected.
        state = await selected_agent.aget_state(run_config)
        interrupt_value = _interrupt_value(state)
        if interrupt_value is None:
            log_event(
                request_id,
                "assistant.resume.failed",
                thread_id_safe=thread_id,
                safe_error_code="no_pending_approval",
            )
            yield _event(
                "error",
                {
                    "code": "no_pending_approval",
                    "message": "No action is waiting for your approval on this thread.",
                },
            )
            return
        action_name = str(interrupt_value["action_requests"][0].get("name", ""))
        allowed = HITL_ALLOWED_DECISIONS.get(action_name, [])
        if decision not in allowed:
            yield _event(
                "error",
                {
                    "code": "invalid_decision",
                    "message": f"Decision '{decision}' is not allowed for {tool_label(action_name)}.",
                },
            )
            return

        # Build the Command(resume=...) decision payload.
        if decision == "edit":
            if not edited_action or not edited_action.get("args"):
                yield _event(
                    "error",
                    {"code": "invalid_edit", "message": "Edit requires the edited action."},
                )
                return
            # MERGE the human's edited values over the ORIGINAL proposal args so
            # identity/project context the model proposed survives the edit; the
            # human can only change the whitelisted editable fields.
            original_args = interrupt_value["action_requests"][0].get("args") or {}
            merged_args = {**original_args, **(edited_action.get("args") or {})}
            resume_decision = {
                "type": "edit",
                "edited_action": {"name": action_name, "args": merged_args},
            }
        elif decision == "reject":
            resume_decision = {"type": "reject", "message": message or "Rejected by user"}
        elif decision == "respond":
            resume_decision = {"type": "respond", "message": message or ""}
        else:
            resume_decision = {"type": "approve"}

        log_event(
            request_id,
            "assistant.hitl.resumed",
            tool=action_name,
            decision=decision,
            thread_id_safe=thread_id,
        )

        async with session_scope(db):
            async for mode, payload in selected_agent.astream(
                Command(resume={"decisions": [resume_decision]}),
                config=run_config,
                context=actor,
                stream_mode=["messages", "updates"],
            ):
                if mode == "updates":
                    for node, update in payload.items():
                        if node == "model":
                            metrics["model_calls"] += 1
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
                                input_tokens=model_turn_usage["input_tokens"],
                                output_tokens=model_turn_usage["output_tokens"],
                                total_tokens=model_turn_usage["total_tokens"],
                            )
                            now = time.perf_counter()
                            for msg in update.get("messages", []):
                                for tool_call in getattr(msg, "tool_calls", None) or []:
                                    name = str(tool_call.get("name", ""))
                                    tool_start_times[name] = now
                                    if name in ai_security.MUTATING_TOOLS:
                                        log_event(
                                            request_id,
                                            "assistant.mutation.started",
                                            tool=name,
                                            thread_id_safe=thread_id,
                                        )
                                    yield _event(
                                        "tool_started",
                                        {"tool": tool_label(name)},
                                    )
                            model_turn_active = False
                        elif node == "tools":
                            for msg in update.get("messages", []):
                                metrics["tool_calls"] += 1
                                content = getattr(msg, "content", None)
                                text = str(content or "")
                                tool_name = str(getattr(msg, "name", ""))
                                ok = not _is_error_result(content)
                                if tool_name in ai_security.MUTATING_TOOLS:
                                    mutation_tool = tool_name
                                    mutation_ok = ok
                                    result_data = _tool_result_data(content)
                                    log_event(
                                        request_id,
                                        "assistant.mutation.completed",
                                        tool=tool_name,
                                        ok=ok,
                                        thread_id_safe=thread_id,
                                        duration_ms=round(
                                            (time.perf_counter() - tool_start_times.pop(tool_name, time.perf_counter())) * 1000
                                        ),
                                        result_chars=len(text),
                                    )
                                    yield _event(
                                        "action_completed",
                                        {
                                            "tool": tool_label(tool_name),
                                            "ok": ok,
                                            "summary": (
                                                str(result_data.get("name") or result_data.get("work_summary") or "")
                                                if result_data
                                                else ""
                                            ),
                                        },
                                    )
                                yield _event(
                                    "tool_finished",
                                    {
                                        "tool": tool_label(tool_name),
                                        "ok": ok,
                                    },
                                )
                                if debug:
                                    log_event(
                                        request_id,
                                        "assistant.tool.completed",
                                        tool=tool_name,
                                        ok=ok,
                                        result_chars=len(text),
                                    )
                else:  # "messages"
                    chunk, meta = payload
                    if meta.get("langgraph_node") == "model":
                        content = getattr(chunk, "content", None)
                        if isinstance(content, str) and content and not getattr(
                            chunk, "tool_calls", None
                        ):
                            final_parts.append(content)
                            yield _event("assistant_token", {"text": content})
                        _capture_usage(getattr(chunk, "usage_metadata", None), metrics)
                        if not model_turn_active:
                            model_turn_active = True
                            model_turn_start = time.perf_counter()
                            model_turn_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
                            log_event(
                                request_id,
                                "assistant.model.started",
                                model_call_number=metrics["model_calls"] + 1,
                                provider=settings.ICE_AI_PROVIDER,
                                model=settings.ICE_AI_MODEL,
                            )
                        _capture_usage(getattr(chunk, "usage_metadata", None), model_turn_usage)

        final_text = "".join(final_parts)
        log_event(
            request_id,
            "assistant.resume.completed",
            decision=decision,
            mutation_tool=mutation_tool,
            mutation_ok=mutation_ok,
            thread_id_safe=thread_id,
            model_calls=metrics["model_calls"],
            tool_calls=metrics["tool_calls"],
            response_chars=len(final_text),
            duration_ms=int((time.perf_counter() - started_at) * 1000),
        )
        yield _event(
            "assistant_complete",
            {
                "request_id": request_id,
                "thread_id": thread_id,
                "memory_mode": mem_mode,
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
        logger.exception("ICE Copilot resume failed (request %s)", request_id)
        log_event(
            request_id,
            "assistant.resume.failed",
            thread_id_safe=thread_id,
            decision=decision,
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
