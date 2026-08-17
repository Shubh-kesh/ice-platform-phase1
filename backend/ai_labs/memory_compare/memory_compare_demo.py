"""LEARNING ONLY — never imported by app/, no network, no DB.

Compare conversation-memory strategies on the observable message flow:

  A. STATELESS (no checkpointer)          — the model forgets every turn
  B. InMemorySaver + thread_id            — the model remembers the thread
  C. InMemorySaver + SummarizationMiddleware — old context is compressed

Uses the SAME fake model + a scratch tool + the SAME user/thread, so the only
difference is the memory strategy. The fake model records what it was given on
each call, so we can see exactly what memory does (and does not) send back.

Run:  python3 memory_compare_demo.py
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langgraph.checkpoint.memory import InMemorySaver


@tool
async def get_project_health(project_code: str, runtime: ToolRuntime[Any] = None) -> dict:  # type: ignore[assignment]
    """Mock project health (no DB)."""
    return {"project_code": project_code, "overall": "green", "budget": "amber"}


class RecordingModel(BaseChatModel):
    responses: list[AIMessage]
    calls: list[list[Any]] = []

    def _generate(self, messages: list[Any], stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(list(messages))
        message = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "RecordingModel":
        return self

    @property
    def _llm_type(self) -> str:
        return "fake-memory"


def _types(calls: list[list[Any]]) -> list[list[str]]:
    return [[type(m).__name__ for m in call] for call in calls]


def _run(mode: str, saver: InMemorySaver | None, middleware: list[Any] | None = None) -> None:
    model = RecordingModel(responses=[AIMessage(content="a1"), AIMessage(content="a2")])
    agent = create_agent(
        model=model,
        tools=[get_project_health],
        system_prompt="sys",
        checkpointer=saver,
        middleware=middleware or [],
    )
    cfg = {"configurable": {"thread_id": "user-1::conv-1"}} if saver else {}
    asyncio.run(agent.ainvoke({"messages": [("user", "q1")]}, config=cfg))
    asyncio.run(agent.ainvoke({"messages": [("user", "q2")]}, config=cfg))
    print(f"[{mode}] model calls: {len(model.calls)}")
    for i, call in enumerate(model.calls, start=1):
        print(f"    call#{i} messages: {_types([call])[0]}")
    blob = " ".join(str(getattr(m, "content", "")) for call in model.calls for m in call)
    print(f"    turn-1 content visible on turn 2? {'q1' in blob and 'a1' in blob}")


def main() -> None:
    print("=" * 74)
    print("A. STATELESS — no checkpointer")
    print("=" * 74)
    _run("A. stateless", None, None)

    print()
    print("=" * 74)
    print("B. InMemorySaver + thread_id")
    print("=" * 74)
    _run("B. saver", InMemorySaver(), None)

    print()
    print("=" * 74)
    print("C. InMemorySaver + SummarizationMiddleware (low trigger)")
    print("=" * 74)
    sum_model = RecordingModel(responses=[AIMessage(content="SUMMARY-CONTENT")])
    _run(
        "C. summarize",
        InMemorySaver(),
        [SummarizationMiddleware(model=sum_model, trigger=("messages", 1), keep=("messages", 1))],
    )

    print()
    print("Key lesson: without a checkpointer the model is stateless; with one")
    print("(keyed by thread_id) prior turns are re-sent as context; with")
    print("summarization the oldest context is compressed into a summary message.")
    print("Memory affects MODEL CONTEXT, never authorization.")


if __name__ == "__main__":
    main()
