"""LEARNING ONLY — never imported by app/, no network, no DB.

ToolRetryMiddleware exponential-backoff timing with a deterministic flaky tool.

The pinned middleware waits `initial_delay * (backoff_factor ** retry_number)`
between attempts (retry_number starts at 0 for the first retry). We compare:

  backoff_factor = 2  -> delays grow: 0.1, 0.2, 0.4 (jitter disabled)
  backoff_factor = 0  -> constant delay: 0.1, 0.1, 0.1

Run:  python3 retry_backoff_demo.py
"""
from __future__ import annotations

import time
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.tools import tool


class Transient(Exception):
    pass


def _flaky_tool():
    stamps: list[float] = []

    @tool
    def flaky(query: str) -> str:
        """A transiently failing external tool."""
        stamps.append(time.perf_counter())
        if len(stamps) < 4:  # fail 3x, succeed on 4th attempt (max_retries=3)
            raise Transient("transient")
        return "ok"

    return flaky, stamps


class Fake(BaseChatModel):
    responses: list[AIMessage]

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        m = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=m)])

    def bind_tools(self, tools, **kwargs):  # noqa: ARG002
        return self

    @property
    def _llm_type(self) -> str:
        return "fake-retry"


def _run(backoff_factor: float, label: str) -> None:
    tool, stamps = _flaky_tool()
    model = Fake(responses=[
        AIMessage(content="", tool_calls=[{"name": "flaky", "args": {"query": "q"}, "id": "c1", "type": "tool_call"}]),
        AIMessage(content="final"),
    ])
    agent = create_agent(
        model=model,
        tools=[tool],
        system_prompt="sys",
        middleware=[
            ToolRetryMiddleware(
                max_retries=3,
                tools=["flaky"],
                retry_on=(Transient,),
                initial_delay=0.1,
                backoff_factor=backoff_factor,
                jitter=False,
                max_delay=5.0,
            )
        ],
    )
    agent.invoke({"messages": [("user", "go")]})
    print(f"[{label}] attempts: {len(stamps)} (expect 4)")
    delays = [round(b - a, 3) for a, b in zip(stamps, stamps[1:])]
    print(f"[{label}] observed waits between attempts: {delays}")


def main() -> None:
    print("=" * 74)
    print("backoff_factor = 2.0 (exponential)")
    print("=" * 74)
    _run(2.0, "factor=2")
    print()
    print("=" * 74)
    print("backoff_factor = 0.0 (constant delay)")
    print("=" * 74)
    _run(0.0, "factor=0")

    print()
    print("retry_number starts at 0 for the FIRST retry, so waits are")
    print("initial_delay * 2^0, 2^1, 2^2 ... = 0.1, 0.2, 0.4 for factor 2.")


if __name__ == "__main__":
    main()
