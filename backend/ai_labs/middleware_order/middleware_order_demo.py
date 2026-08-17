"""LEARNING ONLY — never imported by app/, no network, no DB.

Does middleware order matter? Yes — the FIRST middleware in the stack sees the
event first. Two comparisons with deterministic fakes:

  ORDER A (PII -> Limit -> Retry -> Fallback)  [ICE production order]
  ORDER B (Limit -> PII -> Fallback -> Retry)  [reversed-ish]

Observe:
  - which middleware sees a model failure first
  - whether PII ran before the model saw the message
  - retry-before-fallback vs fallback-before-retry behavior

Run:  python3 middleware_order_demo.py
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    PIIMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration


class ModelTransientError(Exception):
    pass


def model_retry_on(exc):
    return isinstance(exc, ModelTransientError)


class TraceModel(BaseChatModel):
    """Records the messages it receives (to see PII timing) and fails once."""

    calls: list[str] = []
    fail: bool = True

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append("|".join(str(getattr(m, "content", "")) for m in messages))
        if self.fail:
            self.fail = False
            raise ModelTransientError("boom")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "trace"


class Backup(BaseChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="backup-ok"))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "backup"


def _run(order: str, middleware: list[Any]) -> None:
    model = TraceModel()
    agent = create_agent(model=model, tools=[], system_prompt="t", middleware=middleware)
    try:
        r = asyncio.run(agent.ainvoke({"messages": [("user", "mail priya@example.com")]}))
        print(f"[{order}] final: {r['messages'][-1].content}")
    except Exception as e:
        print(f"[{order}] raised: {type(e).__name__}: {str(e)[:60]}")
    seen = model.calls[0] if model.calls else ""
    print(f"[{order}] first model input had redacted email? {'[REDACTED_EMAIL]' in seen}")
    print(f"[{order}] model calls: {len(model.calls)}")


def main() -> None:
    primary = TraceModel()
    pii = PIIMiddleware("email", strategy="redact", apply_to_input=True)
    limit = ModelCallLimitMiddleware(run_limit=8)
    retry = ModelRetryMiddleware(max_retries=1, retry_on=model_retry_on, initial_delay=0.01, jitter=False)
    fallback = ModelFallbackMiddleware(primary, Backup())

    print("=" * 74)
    print("ORDER A — PII -> Limit -> Retry -> Fallback  (ICE production order)")
    print("=" * 74)
    _run("A", [pii, limit, retry, fallback])

    print()
    print("=" * 74)
    print("ORDER B — Limit -> PII -> Fallback -> Retry")
    print("=" * 74)
    _run("B", [limit, pii, fallback, retry])

    print()
    print("Lesson: order changes which middleware sees a failure first and when")
    print("PII is applied. ICE uses ORDER A (PII first so the model never sees raw")
    print("PII; retry before fallback so the same provider is retried first).")


if __name__ == "__main__":
    main()
