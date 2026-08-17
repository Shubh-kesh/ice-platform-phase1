"""LEARNING ONLY — never imported by app/, no network, no DB.

SEQUENTIAL vs PARALLEL tool calling with ICE DB tools + a web tool.

The same question ("how much cement and its market price?") is answered two
ways with a fake model + mock tools that have artificial latency:

  PARALLEL   : get_inventory + web_search requested in the SAME model turn
  SEQUENTIAL : inventory first, then web_search (query informed by inventory)

Measure total elapsed time, model/tool calls, and whether the second tool's
input depended on the first tool's output.

Run:  python3 web_multi_tool_demo.py
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.tools import tool

INVENTORY_LATENCY = 0.2
WEB_LATENCY = 0.3


@tool
async def get_inventory(material: str) -> dict:
    """Get on-hand inventory for a material (mock)."""
    await asyncio.sleep(INVENTORY_LATENCY)
    return {"material": material, "quantity": 420, "unit": "bag"}


@tool
async def web_search(query: str) -> dict:
    """Search the web (mock)."""
    await asyncio.sleep(WEB_LATENCY)
    return {"status": "ok", "results": [{"title": "Market", "url": "https://m", "snippet": f"price reference for {query}"}]}


class Fake(BaseChatModel):
    responses: list[AIMessage]
    calls: list[list[Any]] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(list(messages))
        m = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=m)])

    def bind_tools(self, tools, **kwargs):  # noqa: ARG002
        return self

    @property
    def _llm_type(self) -> str:
        return "fake-multi"


def _run_parallel() -> dict:
    model = Fake(responses=[
        AIMessage(content="", tool_calls=[
            {"name": "get_inventory", "args": {"material": "cement"}, "id": "c1", "type": "tool_call"},
            {"name": "web_search", "args": {"query": "cement market price"}, "id": "c2", "type": "tool_call"},
        ]),
        AIMessage(content="Inventory 420 bags; web shows a price reference."),
    ])
    agent = create_agent(model=model, tools=[get_inventory, web_search], system_prompt="sys")
    t0 = time.perf_counter()
    asyncio.run(agent.ainvoke({"messages": [("user", "cement on hand + market price?")]}))
    return {"model_calls": len(model.calls), "elapsed": round(time.perf_counter() - t0, 2)}


def _run_sequential() -> dict:
    model = Fake(responses=[
        AIMessage(content="", tool_calls=[{"name": "get_inventory", "args": {"material": "cement"}, "id": "c1", "type": "tool_call"}]),
        AIMessage(content="", tool_calls=[{"name": "web_search", "args": {"query": "cement bag market price"}, "id": "c2", "type": "tool_call"}]),
        AIMessage(content="Inventory 420 bags; web shows a price reference."),
    ])
    agent = create_agent(model=model, tools=[get_inventory, web_search], system_prompt="sys")
    t0 = time.perf_counter()
    asyncio.run(agent.ainvoke({"messages": [("user", "cement on hand + market price?")]}))
    return {"model_calls": len(model.calls), "elapsed": round(time.perf_counter() - t0, 2)}


def main() -> None:
    print("=" * 74)
    print("PARALLEL — both tools requested in one model turn")
    print("=" * 74)
    parallel = _run_parallel()
    print(f"  model calls: {parallel['model_calls']} | elapsed: {parallel['elapsed']}s "
          f"(inventory 0.2s + web 0.3s, overlapped)")

    print()
    print("=" * 74)
    print("SEQUENTIAL — web query informed by the inventory result")
    print("=" * 74)
    sequential = _run_sequential()
    print(f"  model calls: {sequential['model_calls']} | elapsed: {sequential['elapsed']}s "
          f"(0.2s + 0.3s, serialized + an extra model turn)")

    print()
    print("Lesson: parallel is faster when the tools are INDEPENDENT; sequential")
    print("is REQUIRED when tool B depends on tool A's result (e.g. the web query")
    print("mentions the material found in inventory). Never claim parallel is always")
    print("better — it depends on the dependency graph.")


if __name__ == "__main__":
    main()
