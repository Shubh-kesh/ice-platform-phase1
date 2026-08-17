"""
ICE Copilot execution logging (AI-1) — safe, observable, learning-friendly.

Two conceptual modes on the SAME logger (`ice.ai`, the existing infra — no
second framework):

- NORMAL: concise operational key=value lines (run lifecycle + metrics).
- DEBUG (ICE_AI_DEBUG=true): richer execution tracing — sanitized query, tool
  arguments, result summaries, message-type sequence. Debug mode NEVER changes
  AI behavior.

Everything here is OBSERVABLE execution tracing only — hidden chain-of-thought
/ model-private reasoning, secrets, system-prompt contents, raw SQL and raw
tool payloads are never logged. Sanitization is centralized in this module so
identity and secrets cannot leak through future tool arguments.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("ice.ai")

# Keys that must never be serialized as tool arguments / log fields, even in
# debug mode. Identity comes from ToolRuntime.context, not tool arguments, but
# this is a defensive backstop.
_FORBIDDEN_ARG_KEYS = frozenset(
    {
        "user_id",
        "role",
        "email",
        "actor",
        "api_key",
        "token",
        "refresh_token",
        "password",
        "authorization",
    }
)

# Hard secrets never logged anywhere.
_FORBIDDEN_FIELD_NAMES = frozenset(
    {"api_key", "openai_api_key", "anthropic_api_key", "groq_api_key", "openrouter_api_key",
     "authorization", "refresh_token", "password", "cookie", "secret"}
)

_MAX_VALUE_CHARS = 80
_MAX_QUERY_CHARS = 200


def _fmt(value: Any) -> str:
    if isinstance(value, (dict, list)):
        try:
            # compact separators keep the serialized value a single token
            return json.dumps(value, separators=(",", ":"), default=str, ensure_ascii=False)
        except TypeError:
            return str(value)
    return str(value)


def _truncate(text: str, limit: int = _MAX_VALUE_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _render(key: str, value: Any) -> str:
    text = _fmt(value)
    if any(ch.isspace() for ch in text):
        # values containing whitespace are quoted so the line stays parseable
        return f'{key}="{text.replace(chr(34), chr(39))}"'
    return f"{key}={text}"


def log_event(request_id: str, event: str, **fields: Any) -> None:
    """Emit one structured `event=... request_id=... key=value` line.

    Any field whose NAME matches a hard-secret name is dropped defensively.
    """
    parts = [f"event={event}", f"request_id={request_id}"]
    for key, value in fields.items():
        if value is None:
            continue
        if key.lower() in _FORBIDDEN_FIELD_NAMES:
            continue
        parts.append(_render(key, value))
    logger.info(" ".join(parts))


def sanitize_query(query: str) -> str:
    """A sanitized, truncated copy of the user query for DEBUG logs.

    PII (email/phone/Aadhaar/PAN) is masked so ICE_AI_DEBUG can never defeat
    PIIMiddleware by writing raw PII before the middleware masks it.
    """
    from app.ai import pii as ai_pii

    return _truncate(ai_pii.mask_pii_text(str(query)), _MAX_QUERY_CHARS)


def sanitize_tool_args(args: Any) -> dict[str, Any]:
    """Model-visible tool arguments reduced to a safe DEBUG representation.

    Forbidden identity/secret keys are dropped; every value is truncated.
    """
    if not isinstance(args, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in args.items():
        if key in _FORBIDDEN_ARG_KEYS:
            continue
        safe[key] = _truncate(_fmt(value))
    return safe


def summarize_tool_result(tool_name: str, result: Any) -> dict[str, Any]:
    """A compact, safe summary of a structured tool result for DEBUG logs.

    Keeps counts/status/flags, never raw rows or full payloads.
    """
    if not isinstance(result, dict):
        return {"status": "ok"} if result is not None else {"status": "empty"}
    if result.get("error"):
        return {"status": "error", "error": str(result["error"])}
    summary: dict[str, Any] = {"status": "ok"}
    for key in ("total_count", "returned_count", "truncated", "po_count"):
        if key in result:
            summary[key] = result[key]
    if "overall" in result and isinstance(result["overall"], dict):
        summary["overall"] = result["overall"].get("value")
    if tool_name == "get_project_health":
        for dim in ("timeline", "budget", "safety"):
            value = result.get(dim)
            if isinstance(value, dict) and value.get("value"):
                summary[dim] = value["value"]
    if tool_name == "get_project_inventory" and "returned_count" in result:
        summary["item_count"] = result["returned_count"]
    if tool_name == "get_purchase_orders" and "returned_count" in result:
        summary["po_count"] = result["returned_count"]
    if "by_cost_code" in result and isinstance(result["by_cost_code"], dict):
        summary["cost_code_count"] = len(result["by_cost_code"])
    return summary


def message_type_summary(message: Any) -> str:
    """A safe TYPE-only summary of a LangChain message (never its content).

    Examples: "HumanMessage", "AIMessage(tool_calls=1)", "ToolMessage(tool=...)".
    """
    name = type(message).__name__
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return f"AIMessage(tool_calls={len(tool_calls)})"
    tool_name = getattr(message, "name", None)
    if name == "ToolMessage":
        return f"ToolMessage(tool={tool_name or '?'})"
    return name


def tool_count_summary(metrics: dict[str, int]) -> dict[str, int]:
    """Per-tool call counts (e.g. {"list_projects": 1, "get_project_health": 12})
    so the N+1 portfolio pattern is observable at run completion."""
    return dict(metrics)
