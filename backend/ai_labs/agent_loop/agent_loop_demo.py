"""LEARNING ONLY — never imported by app/, no network, no DB.

Make the agent loop observable with a fake model and a fake ICE-like tool:

  HumanMessage
    -> model receives available tools
    -> AIMessage containing a tool call
    -> tool executes
    -> ToolMessage
    -> model continues
    -> final AIMessage

The fake model records every input it was given, so we can print exactly what
was sent to the model at each step. Token/usage metadata is attached by the
fake on the final chunk, as a real provider would.

Run:  python3 agent_loop_demo.py
"""
from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatResult, ChatGeneration


@tool
async def get_project_status(project_code: str, runtime: ToolRuntime[Any] = None) -> dict:  # type: ignore[assignment]
    """Get the current status of a project (mock data - no DB)."""
    return {
        "project_code": project_code,
        "status": "active",
        "percent_complete": 45,
        "health": "amber",
    }


class LoopRecordingModel(BaseChatModel):
    """Fake model that records every input it receives and replays scripted
    replies: first an AIMessage with a tool call, then a final answer."""

    calls: list[list[Any]] = []

    def _generate(self, messages: list[Any], stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(list(messages))
        message = (
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_project_status",
                        "args": {"project_code": "PRJ-2026-0001"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
            if len(self.calls) == 1
            else AIMessage(
                content="Project PRJ-2026-0001 is active, 45% complete, health amber.",
                usage_metadata={"input_tokens": 88, "output_tokens": 14, "total_tokens": 102},
            )
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "LoopRecordingModel":
        return self

    @property
    def _llm_type(self) -> str:
        return "fake-loop"


async def main() -> None:
    model = LoopRecordingModel()
    agent = create_agent(
        model=model,
        tools=[get_project_status],
        system_prompt="You are a read-only ICE assistant.",
    )
    first_input = [HumanMessage(content="What is the status of PRJ-2026-0001?")]

    print("=" * 74)
    print("STEP 1 - messages that exist before the FIRST model call")
    print("=" * 74)
    for m in first_input:
        print(f"  {type(m).__name__}: {m.content!r}")

    print()
    print("=" * 74)
    print("STEP 2 - what the model is given: the tool schema")
    print("=" * 74)
    print("  model-visible args:", get_project_status.args)

    import time
    started = time.perf_counter()
    result = await agent.ainvoke({"messages": first_input})

    print()
    print("=" * 74)
    print("STEP 3 - the full message timeline produced by the loop")
    print("=" * 74)
    for m in result["messages"]:
        kind = type(m).__name__
        if getattr(m, "tool_calls", None):
            print(f"  {kind}: tool_calls={m.tool_calls}")
        else:
            print(f"  {kind}: {str(getattr(m, 'content', ''))[:90]!r}")

    print()
    print("=" * 74)
    print("STEP 4 - messages supplied to EACH model call (recorded by the fake)")
    print("=" * 74)
    for i, inputs in enumerate(model.calls, start=1):
        print(f"  call #{i} input messages:")
        for m in inputs:
            kind = type(m).__name__
            if getattr(m, "tool_calls", None):
                print(f"    {kind}: tool_calls={m.tool_calls}")
            else:
                print(f"    {kind}: {str(getattr(m, 'content', ''))[:90]!r}")
    print("  -> note: call #2 sees HumanMessage + AIMessage(tool call) + ToolMessage")

    print()
    print("=" * 74)
    print("STEP 5 - the final AIMessage + provider usage metadata")
    print("=" * 74)
    final = result["messages"][-1]
    print(f"  content: {final.content!r}")
    print(f"  usage_metadata: {final.usage_metadata}")

    print()
    print("=" * 74)
    print("RUN METRICS (execution observability, not reasoning)")
    print("=" * 74)
    tool_msgs = [m for m in result["messages"] if type(m).__name__ == "ToolMessage"]
    print(f"  model calls : {len(model.calls)}")
    print(f"  tool calls  : {len(tool_msgs)}")
    print(f"  duration    : {int((time.perf_counter() - started) * 1000)} ms")
    print(f"  tokens      : {final.usage_metadata}")
    print("  tool counts : get_project_status = 1")

    print()
    print("Key lesson: tool calling is NOT a single LLM response. The model")
    print("requests a tool (AIMessage.tool_calls); the harness runs it and feeds")
    print("the result back as a ToolMessage; only then does the model produce the")
    print("final answer. This is the loop the ICE Copilot adapter translates into")
    print("its stable SSE events.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
