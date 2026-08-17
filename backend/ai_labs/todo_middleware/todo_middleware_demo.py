"""LEARNING ONLY — never imported by app/, no network, no DB.

TodoListMiddleware adds a `write_todos` planning tool so the model can break a
complex objective into tracked steps. Compare a complex-review agent WITH and
WITHOUT the middleware:

  WITHOUT: no write_todos tool; the model may do the work ad hoc.
  WITH   : the write_todos planning tool is available to the model.

Scoring rubric for the real (live) comparison later:
  health considered +1, schedule +1, budget +1 (role permitting), inventory +1,
  procurement +1 (role permitting), recommendations grounded in data +1 (max 6).

This deterministic demo measures the mechanics (tool availability, model calls),
not subjective quality. Run:  python3 todo_middleware_demo.py
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration


class Fake(BaseChatModel):
    responses: list[AIMessage]
    calls: list[Any] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        m = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=m)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fake-todo"


def _run(middleware, label) -> None:
    model = Fake(responses=[AIMessage(content="Here are the top five actions for Green Heights.")])
    agent = create_agent(model=model, tools=[], system_prompt="t", middleware=middleware)
    r = asyncio.run(agent.ainvoke({"messages": [("user", "Review Green Heights across schedule, health, budget, inventory and procurement and give the five highest-priority actions.")]}))
    print(f"[{label}] model calls: {len(model.calls)} | final: {r['messages'][-1].content[:50]!r}")


def main() -> None:
    print("=" * 74)
    print("WITHOUT TodoListMiddleware")
    print("=" * 74)
    _run([], "without")

    print()
    print("=" * 74)
    print("WITH TodoListMiddleware (adds the write_todos planning tool)")
    print("=" * 74)
    _run([TodoListMiddleware()], "with")

    print()
    print("Note: TodoListMiddleware is OPTIONAL (ICE_AI_TODO_ENABLED). It adds a")
    print("read-only planning tool; it never authorizes ICE tools — every tool")
    print("still self-authorizes. For a complex review it can make the agent plan")
    print("first; the live rubric above scores the final answer.")


if __name__ == "__main__":
    main()
