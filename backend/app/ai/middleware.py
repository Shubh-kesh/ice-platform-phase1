"""
ICE Copilot middleware factory (W7.3).

Builds the full Weekend-07 middleware stack in ONE explicit, inspectable order.
Identity is NEVER placed in middleware-generated model arguments — ActorContext
remains the invocation context (`context=actor`). Order is justified by the
`backend/ai_labs/middleware_order/` experiment + the installed middleware
implementations:

  PII (input) -> Summarization/ContextEdit (memory) -> ModelCallLimit ->
  ModelRetry -> ModelFallback -> LLMToolSelector -> ToolCallLimit (global +
  per-tool web) -> ToolRetry (web external)

Product-vs-learning:
  PII email/phone, ModelCallLimit, ModelRetry, ToolCallLimit, ToolRetry  -> PRODUCT
  ModelFallback, TodoList, LLMToolSelector                                -> OPTIONAL/measurement-gated
  custom Aadhaar/PAN detectors, ToolErrorMiddleware                       -> LEARNING
"""
from __future__ import annotations

from typing import Any, cast

from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    LLMToolSelectorMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    PIIMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)

from app.ai import pii as ai_pii
from app.ai import web_search as ai_web_search
from app.ai import memory as ai_memory
from app.ai.security import TOOL_WEB_SEARCH
from app.core.config import settings


class ModelTransientError(Exception):
    """Transient model failure used by tests/labs (mirrors SDK transient errors)."""


def model_retry_on(exc: Exception) -> bool:
    """Retry only transient provider failures (timeout/connection/429/5xx).

    NEVER retries auth, invalid-request, or other deterministic config errors.
    Matches common provider SDK exception names by substring.
    """
    name = type(exc).__name__.lower()
    if name in {"modeltransienterror", "timeouterror", "connectionerror"}:
        return True
    for token in ("timeout", "connection", "ratelimit", "rate_limit", "internal_server", "apistatus"):
        if token in name:
            return True
    return False


def build_middleware(
    memory_mode: str,
    primary_model: Any = None,
    summarization_model: Any = None,
    fallback_model: Any = None,
    selector_model: Any = None,
) -> list[Any]:
    """Construct the ordered middleware stack from settings. Never raises for a
    merely-optional feature; safe defaults apply."""
    stack: list[Any] = []

    # 1. PII on input (product: email + phone; custom Aadhaar/PAN learning).
    if settings.ICE_AI_PII_ENABLED:
        strategy: Any = cast(Any, settings.ICE_AI_PII_STRATEGY)
        stack.append(PIIMiddleware("email", strategy=strategy, apply_to_input=True))
        stack.append(
            PIIMiddleware(
                "phone",
                strategy=strategy,
                detector=cast(Any, ai_pii.detect_phone),
                apply_to_input=True,
            )
        )
        if settings.ICE_AI_PII_CUSTOM_ENABLED:
            stack.append(
                PIIMiddleware(
                    "aadhaar",
                    strategy=strategy,
                    detector=cast(Any, ai_pii.detect_aadhaar),
                    apply_to_input=True,
                    apply_to_tool_results=True,
                )
            )
            stack.append(
                PIIMiddleware(
                    "pan",
                    strategy=strategy,
                    detector=cast(Any, ai_pii.detect_pan),
                    apply_to_input=True,
                )
            )

    # 2. W7.1 memory middleware (compress/edit context before the model call).
    if memory_mode == ai_memory.MEMORY_MODE_SUMMARIZE and summarization_model is not None:
        trigger: Any = (
            cast(Any, settings.ICE_AI_SUMMARIZE_TRIGGER_KIND),
            settings.ICE_AI_SUMMARIZE_TRIGGER_VALUE,
        )
        stack.append(
            SummarizationMiddleware(
                model=summarization_model,
                trigger=trigger,
                keep=("messages", settings.ICE_AI_SUMMARIZE_KEEP),
            )
        )
    elif memory_mode == ai_memory.MEMORY_MODE_CONTEXT_EDIT:
        stack.append(
            ContextEditingMiddleware(
                edits=[
                    ClearToolUsesEdit(
                        trigger=settings.ICE_AI_CONTEXT_EDIT_TRIGGER,
                        keep=settings.ICE_AI_CONTEXT_EDIT_KEEP,
                        clear_tool_inputs=True,
                    )
                ]
            )
        )

    # 3. Model call limit — bounds runaway loops (run + optional thread).
    if settings.ICE_AI_MODEL_RUN_LIMIT > 0 or settings.ICE_AI_MODEL_THREAD_LIMIT > 0:
        stack.append(
            ModelCallLimitMiddleware(
                run_limit=settings.ICE_AI_MODEL_RUN_LIMIT or None,
                thread_limit=settings.ICE_AI_MODEL_THREAD_LIMIT or None,
                exit_behavior=settings.ICE_AI_MODEL_LIMIT_EXIT,  # type: ignore[arg-type]
            )
        )

    # 4. Model retry — transient same-provider failures.
    stack.append(
        ModelRetryMiddleware(
            max_retries=settings.ICE_AI_MODEL_RETRY_MAX,
            retry_on=model_retry_on,
            initial_delay=settings.ICE_AI_MODEL_RETRY_INITIAL_DELAY,
            backoff_factor=settings.ICE_AI_MODEL_RETRY_BACKOFF,
            max_delay=5.0,
            jitter=True,
        )
    )

    # 5. Model fallback — server-side failover (only when configured).
    if fallback_model is not None and primary_model is not None:
        stack.append(ModelFallbackMiddleware(primary_model, fallback_model))

    # 6. LLM tool selector — measurement-gated; narrows the AUTHORIZED toolset.
    if settings.ICE_AI_TOOL_SELECTOR_ENABLED and selector_model is not None:
        stack.append(
            LLMToolSelectorMiddleware(
                model=selector_model,
                max_tools=settings.ICE_AI_TOOL_SELECTOR_MAX_TOOLS,
                always_include=[
                    t.strip()
                    for t in settings.ICE_AI_TOOL_SELECTOR_ALWAYS_INCLUDE.split(",")
                    if t.strip()
                ],
            )
        )

    # 7. Tool call limits — global + a tight per-tool cap on web_search.
    # Verified behavior (W7.3): the counts persist via the checkpointer-backed
    # thread counter, so a THREAD limit + exit_behavior='end' is what actually
    # enforces (run-only counting did not persist through create_agent in the
    # pinned version). Thread limits are only set when memory (checkpointer) is
    # active; otherwise ModelCallLimit remains the effective guard.
    thread_limit = (
        (settings.ICE_AI_TOOL_THREAD_LIMIT or None)
        if memory_mode != ai_memory.MEMORY_MODE_NONE
        else None
    )
    run_limit = settings.ICE_AI_TOOL_RUN_LIMIT or None
    stack.append(
        ToolCallLimitMiddleware(
            run_limit=run_limit,
            thread_limit=thread_limit,
            exit_behavior="end",
        )
    )
    if settings.ICE_AI_WEB_TOOL_RUN_LIMIT > 0 and settings.ICE_AI_WEB_SEARCH_ENABLED:
        stack.append(
            ToolCallLimitMiddleware(
                tool_name=TOOL_WEB_SEARCH,
                run_limit=settings.ICE_AI_WEB_TOOL_RUN_LIMIT,
                thread_limit=thread_limit,
                exit_behavior="end",
            )
        )

    # 8. Tool retry — transient external failures ONLY (scoped to web_search).
    if settings.ICE_AI_WEB_SEARCH_ENABLED:
        stack.append(
            ToolRetryMiddleware(
                max_retries=settings.ICE_AI_WEB_SEARCH_RETRIES,
                tools=[TOOL_WEB_SEARCH],
                retry_on=(ai_web_search.WebSearchTransientError,),
                on_failure=ai_web_search.on_retry_failure,
                initial_delay=settings.ICE_AI_WEB_SEARCH_RETRY_INITIAL_DELAY,
                backoff_factor=settings.ICE_AI_WEB_SEARCH_RETRY_BACKOFF,
                jitter=True,
                max_delay=5.0,
            )
        )

    return stack
