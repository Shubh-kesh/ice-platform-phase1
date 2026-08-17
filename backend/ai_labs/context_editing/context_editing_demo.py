"""LEARNING ONLY — never imported by app/, no network, no DB.

STORED CONVERSATION vs ACTIVE MODEL CONTEXT.

With a checkpointer, every ToolMessage/result is STORED in the thread. But on
the NEXT model call, does the model see the full history, or can context
editing shrink what is actually sent?

Compare, over 3 turns with a large-ish tool result:

  A. FULL tool history — the model sees every old ToolMessage verbatim
  B. ContextEditingMiddleware + ClearToolUsesEdit — old tool uses are cleared
     to a placeholder, shrinking the active model context

The fake model records the messages it is given on each call, so we can see
exactly what the model context contained — never chain-of-thought.

Run:  python3 context_editing_demo.py
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ClearToolUsesEdit, ContextEditingMiddleware
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langgraph.checkpoint.memory import InMemorySaver


@tool
async def get_inventory(project_code: str, runtime: ToolRuntime[Any] = None) -> dict:  # type: ignore[assignment]
    """Mock a large inventory result (no DB)."""
    return {
        "items": [{"name": f"Item-{i}", "qty": 100 + i} for i in range(20)],
        "total_count": 20,
        "returned_count": 20,
        "truncated": False,
    }


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
        return "fake-ctx"


def _call_tool() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "get_inventory", "args": {"project_code": "PRJ-1"}, "id": "c1", "type": "tool_call"}],
    )


def _run(mode: str, middleware: list[Any] | None) -> None:
    model = RecordingModel(
        responses=[_call_tool(), AIMessage(content="inv1"), _call_tool(), AIMessage(content="inv2")]
    )
    agent = create_agent(
        model=model,
        tools=[get_inventory],
        system_prompt="sys",
        checkpointer=InMemorySaver(),
        middleware=middleware or [],
    )
    cfg = {"configurable": {"thread_id": "user-1::conv-1"}}
    # turn 1: inventory -> large result; turn 2: another inventory call
    asyncio.run(agent.ainvoke({"messages": [("user", "inventory?")]}, config=cfg))
    asyncio.run(agent.ainvoke({"messages": [("user", "again?")]}, config=cfg))
    last_input = model.calls[-1]
    joined = " ".join(str(getattr(m, "content", "")) for m in last_input)
    has_old = "Item-5" in joined
    has_cleared = "[cleared]" in joined
    total_chars = sum(len(str(getattr(m, "content", ""))) for m in last_input)
    print(f"[{mode}] model-call-2 input chars: {total_chars}")
    print(f"    contains turn-1 tool result ('Item-5')? {has_old}")
    print(f"    contains placeholder '[cleared]'?     {has_cleared}")


def main() -> None:
    print("=" * 74)
    print("A. FULL tool history (saver only)")
    print("=" * 74)
    _run("A. full history", None)

    print()
    print("=" * 74)
    print("B. ContextEditing + ClearToolUsesEdit (keep=1, low trigger)")
    print("=" * 74)
    _run("B. context-edit", [ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=1, keep=1)])])

    print()
    print("Key lesson: stored conversation (checkpoint) != active model context.")
    print("ContextEditingMiddleware/ClearToolUsesEdit shrink what the model sees")
    print("on the next call without deleting the stored history. That is exactly")
    print("the 'stored vs context' distinction W7.1 wants documented.")


if __name__ == "__main__":
    main()
