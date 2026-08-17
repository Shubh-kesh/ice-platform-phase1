"""LEARNING ONLY — never imported by app/, no network, no DB.

return_direct: when a tool's result is already final/user-ready, the graph can
skip the extra model call and return the tool output directly.

  return_direct=False -> tool result -> model call -> final answer (2 calls)
  return_direct=True  -> tool result -> immediate return          (1 call)

Run:  python3 return_direct_demo.py
"""
from __future__ import annotations

import asyncio

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool


class Fake(BaseChatModel):
    responses: list[AIMessage]
    n_calls: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.n_calls += 1
        return ChatResult(
            generations=[ChatGeneration(message=self.responses.pop(0) if self.responses else AIMessage(content="Done"))]
        )

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fake-rd"


@tool
def current_cement_rate(city: str) -> str:
    """Exact current cement rate per bag (read-only, ICE-like)."""
    return "Rs 420/bag"


def tc():
    return AIMessage(content="", tool_calls=[{"name": "current_cement_rate", "args": {"city": "pune"}, "id": "c1", "type": "tool_call"}])


def main() -> None:
    print("=" * 74)
    for direct in (False, True):
        t = current_cement_rate if not direct else current_cement_rate.model_copy(update={"return_direct": True})
        model = Fake(responses=[tc(), AIMessage(content="Cement is Rs 420 per bag.")])
        agent = create_agent(model=model, tools=[t])
        out = asyncio.run(agent.ainvoke({"messages": [("user", "cement rate in pune?")]}))
        print(f"return_direct={str(direct):5s} | model_calls={model.n_calls} | final={out['messages'][-1].content!r}")
    print("=" * 74)
    print("return_direct saves a model call but SKIPS the model's framing/answer")
    print("tone. ICE: LEARNING ONLY — tool results are data, not final user copy;")
    print("do not apply globally.")


if __name__ == "__main__":
    main()
