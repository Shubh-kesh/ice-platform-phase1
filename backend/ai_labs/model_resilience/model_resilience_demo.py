"""LEARNING ONLY — never imported by app/, no network, no DB.

MODEL RETRY vs MODEL FALLBACK — the decision ICE makes.

  RETRY    : same provider/model, transient failure, exponential backoff.
  FALLBACK : different provider/model when the primary is unavailable.

Compare A (none), B (retry only), C (fallback only), D (retry then fallback)
on a primary that fails once then succeeds (so retry wins) and a primary that
always fails (so fallback must win).

Run:  python3 model_resilience_demo.py
"""
from __future__ import annotations

import asyncio
import time
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration


class ModelTransientError(Exception):
    pass


def retry_on(exc):
    return isinstance(exc, ModelTransientError)


class FlakyOnce(BaseChatModel):
    """Fails once then succeeds (retry should win)."""

    calls: list[float] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(time.perf_counter())
        if len(self.calls) == 1:
            raise ModelTransientError("transient")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="primary-ok"))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "flaky-once"


class AlwaysDown(BaseChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise ModelTransientError("always down")

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "always-down"


class Backup(BaseChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="backup-ok"))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "backup"


def _invoke(middleware, model, label):
    agent = create_agent(model=model, tools=[], system_prompt="t", middleware=middleware)
    t0 = time.perf_counter()
    try:
        r = asyncio.run(agent.ainvoke({"messages": [("user", "hi")]}))
        print(f"[{label}] final={r['messages'][-1].content!r} elapsed={round(time.perf_counter()-t0, 2)}s")
    except Exception as e:
        print(f"[{label}] raised {type(e).__name__}: {str(e)[:50]} elapsed={round(time.perf_counter()-t0, 2)}s")


def main() -> None:
    retry = ModelRetryMiddleware(max_retries=1, retry_on=retry_on, initial_delay=0.05, backoff_factor=2.0, jitter=False)

    print("Primary fails once then succeeds (RETRY should win):")
    f1 = FlakyOnce()
    _invoke([], f1, "A none")
    f2 = FlakyOnce()
    _invoke([retry], f2, "B retry")
    f3 = FlakyOnce()
    _invoke([ModelFallbackMiddleware(f3, Backup())], f3, "C fallback")
    f4 = FlakyOnce()
    _invoke([retry, ModelFallbackMiddleware(f4, Backup())], f4, "D retry+fallback")
    print(f"  B primary attempts (retry): {len(f2.calls)} | C primary attempts (fallback): {len(f3.calls)}")

    print("Primary ALWAYS down (FALLBACK must win):")
    ad = AlwaysDown()
    _invoke([retry, ModelFallbackMiddleware(ad, Backup())], ad, "D always-down")


if __name__ == "__main__":
    main()
