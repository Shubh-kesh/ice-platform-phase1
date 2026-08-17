"""LEARNING ONLY — never imported by app/, no network, no DB.

Dynamic tool gating: hide tools from the model's menu for a call (defense in
depth / token reduction) — NOT authorization. Hard per-tool RBAC stays in the
tool itself, exactly like ICE.

  STATIC  : the whole role-filtered toolset is bound at agent build time.
  DYNAMIC : a wrap_model_call middleware narrows the tools the MODEL sees for
            each request (e.g. a client sees no finance tools this turn).

The FINAL authorization boundary is the tool's own self-check from
ToolRuntime.context — gating only shrinks what the model can propose.

Run:  python3 tool_gating_demo.py
"""
from __future__ import annotations

import asyncio

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool


@tool
def get_project_budget(project_id: str) -> str:
    """Finance surface — self-authorizes from runtime context (not shown here)."""
    return "budget: 1M"


@tool
def list_projects(project_id: str) -> str:
    """Read-only project list."""
    return "[PRJ-2026-0001]"


class Fake(BaseChatModel):
    responses: list[AIMessage]
    seen_tools: list = []
    _current: list[str] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen_tools.append(sorted(list(self._current)))
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0) if self.responses else AIMessage(content="Done"))])

    def bind_tools(self, tools, **kwargs):
        self._current = [getattr(t, "name", str(t)) for t in tools] if tools else []
        return self

    @property
    def _llm_type(self):
        return "fake-gate"


def _agent(model, tools):
    return create_agent(model=model, tools=tools, system_prompt="t")


def main() -> None:
    print("=" * 74)
    print("STATIC role-filtered toolset (both tools bound for an internal role)")
    print("=" * 74)
    m1 = Fake(responses=[AIMessage(content="ok")])
    agent1 = _agent(m1, [list_projects, get_project_budget])
    asyncio.run(agent1.ainvoke({"messages": [("user", "go")]}))
    print(f"model-visible tools: {m1.seen_tools}")

    print()
    print("=" * 74)
    print("DYNAMIC gating via wrap_model_call (finance removed for a client)")
    print("=" * 74)

    @wrap_model_call
    async def gate_model_call(request, handler):
        # A client never sees finance tools this turn — still NOT authorization.
        request.tools = [t for t in request.tools if t.name != "get_project_budget"]
        return await handler(request)

    m2 = Fake(responses=[AIMessage(content="ok")])
    agent2 = create_agent(
        model=m2,
        tools=[list_projects, get_project_budget],
        system_prompt="t",
        middleware=[gate_model_call],
    )
    asyncio.run(agent2.ainvoke({"messages": [("user", "go")]}))
    print(f"model-visible tools (gated): {m2.seen_tools}")
    print()
    print("ICE: role-filtered catalog already prunes the menu statically; dynamic")
    print("gating is defense-in-depth/token reduction, NOT authorization — every")
    print("tool still re-checks RBAC from ToolRuntime.context.")


if __name__ == "__main__":
    main()
