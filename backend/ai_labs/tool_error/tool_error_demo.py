"""LEARNING ONLY — never imported by app/, no network, no DB.

TOOL ERROR handling — compare the ICE approach (safe_tool) with
ToolErrorMiddleware on raw-raising tools.

ICE PRODUCT decision (from this experiment): KEEP safe_tool for deterministic
domain/RBAC errors (they are typed conditions the model should see) and let
unexpected exceptions also be caught by safe_tool -> safe dicts. ToolErrorMiddleware
is LEARNING ONLY here because ICE tools never leak raw exceptions (safe_tool
already converts them), so a generic middleware would be redundant and could
mangle RBAC denials if misordered.

Run:  python3 tool_error_demo.py
"""
from __future__ import annotations

import asyncio
import json
from langchain.agents import create_agent
from langchain.agents.middleware import ToolErrorMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.tools import tool


@tool
def domain_denied(x: int = 1) -> str:
    """A deterministic domain/RBAC-style denial."""
    return json.dumps({"error": "not_permitted", "detail": "not visible"})


@tool
def raw_explodes(x: int = 1) -> str:
    """A raw-raising tool (what safe_tool prevents)."""
    raise RuntimeError("secret db password hash")


@tool
def raw_external(x: int = 1) -> str:
    """A transient external failure."""
    raise ConnectionError("external service down")


def _cb(exc, request=None):
    return f"safe message for {type(exc).__name__}"


def _call(agent, model, label):
    r = asyncio.run(agent.ainvoke({"messages": [("user", "go")]}))
    tool_msg = [m for m in r["messages"] if m.type == "tool"][0].content
    print(f"[{label}] model saw: {str(tool_msg)[:70]}")


class Fake(BaseChatModel):
    responses: list[AIMessage]

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        m = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=m)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fake"


def _tc(name):
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": "c1", "type": "tool_call"}])


def main() -> None:
    print("=" * 74)
    print("safe_tool behavior (ICE product): deterministic dicts, no exceptions leak")
    print("=" * 74)
    agent = create_agent(model=Fake(responses=[_tc("domain_denied"), AIMessage(content="ok")]), tools=[domain_denied], system_prompt="t")
    _call(agent, Fake, "domain_denied (safe_tool-equivalent)")

    print()
    print("=" * 74)
    print("ToolErrorMiddleware on raw-raising tools")
    print("=" * 74)
    agent2 = create_agent(model=Fake(responses=[_tc("raw_explodes"), AIMessage(content="ok")]), tools=[raw_explodes], system_prompt="t",
                          middleware=[ToolErrorMiddleware(_cb)])
    _call(agent2, Fake, "raw_explodes + ToolError")

    agent3 = create_agent(model=Fake(responses=[_tc("raw_external"), AIMessage(content="ok")]), tools=[raw_external], system_prompt="t",
                          middleware=[ToolErrorMiddleware(_cb)])
    _call(agent3, Fake, "raw_external + ToolError")

    print()
    print("ICE product: keep safe_tool (typed domain errors + safe internal fallback);")
    print("ToolErrorMiddleware stays LEARNING ONLY because ICE tools already convert")
    print("unexpected exceptions to safe dicts and RBAC denials must stay typed.")


if __name__ == "__main__":
    main()
