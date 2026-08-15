"""LEARNING ONLY — never imported by app/, no network, no DB.

Compare a hand-written agentic loop (Class-05 style) with LangChain's
create_agent, using the SAME fake model + the SAME simple read-only tool and
question, so the only difference is the orchestration.

Manual loop: you write the message list, dispatch tool calls, and decide when
to stop. create_agent: the harness does all of that for you.

Run:  python3 create_agent_vs_manual_demo.py
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatResult, ChatGeneration

MAX_TURNS = 5


@tool
async def get_project_status(project_code: str, runtime: ToolRuntime[Any] = None) -> dict:  # type: ignore[assignment]
    """Get the current status of a project (mock data - no DB)."""
    return {
        "project_code": project_code,
        "status": "active",
        "percent_complete": 45,
        "health": "amber",
    }


class LoopModel(BaseChatModel):
    """Same scripted fake for BOTH loops: call 1 asks for the tool, call 2 answers."""

    calls: list[int] = []

    def _generate(self, messages: list[Any], stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(len(messages))
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
            else AIMessage(content="PRJ-2026-0001 is active, 45% complete, health amber.")
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "LoopModel":
        return self

    @property
    def _llm_type(self) -> str:
        return "fake-compare"


async def _dispatch(name: str, args: dict[str, Any]) -> Any:
    # Manual dispatch: call the tool's underlying coroutine directly (the
    # ToolRuntime param is irrelevant to this mock tool).
    return await get_project_status.coroutine(**args, runtime=None)


def manual_loop(model: BaseChatModel, question: str) -> str:
    """Hand-written agentic loop (Class-05 pattern, LangChain message API)."""
    messages: list[Any] = [
        SystemMessage(content="You are a read-only ICE assistant."),
        HumanMessage(content=question),
    ]
    for _ in range(MAX_TURNS):
        reply = model.invoke(messages)
        messages.append(reply)
        if not getattr(reply, "tool_calls", None):
            return str(reply.content)
        for call in reply.tool_calls:
            result = asyncio.run(_dispatch(call["name"], call["args"]))
            messages.append(
                ToolMessage(content=str(result), tool_call_id=call["id"], name=call["name"])
            )
    return "Reached max turns without a final answer."


async def create_agent_loop(model: BaseChatModel, question: str) -> str:
    agent = create_agent(
        model=model,
        tools=[get_project_status],
        system_prompt="You are a read-only ICE assistant.",
    )
    result = await agent.ainvoke({"messages": [("user", question)]})
    return str(result["messages"][-1].content)


def main() -> None:
    question = "What is the status of PRJ-2026-0001?"

    print("=" * 74)
    print("MANUAL LOOP — you write the orchestration")
    print("=" * 74)
    manual_model = LoopModel()
    manual_answer = manual_loop(manual_model, question)
    print(f"  answer: {manual_answer!r}")
    print(f"  model was called {len(manual_model.calls)}x with message-lists of sizes {manual_model.calls}")
    print("  what YOU had to write:")
    print("    - build messages: system + human")
    print("    - call the model, append AIMessage")
    print("    - detect tool_calls and dispatch each by name")
    print("    - build ToolMessage per result and re-append")
    print("    - decide when to stop (max_turns guard)")
    print()

    print("=" * 74)
    print("CREATE_AGENT — the harness writes the orchestration")
    print("=" * 74)
    create_model = LoopModel()
    create_answer = asyncio.run(create_agent_loop(create_model, question))
    print(f"  answer: {create_answer!r}")
    print(f"  model was called {len(create_model.calls)}x with message-lists of sizes {create_model.calls}")
    print()

    print("=" * 74)
    print("WHAT CREATE_AGENT ABSTRACTS")
    print("=" * 74)
    print("  - tool schema binding (bind_tools) and the tool registry")
    print("  - the message list lifecycle (Human/AI/Tool message handling)")
    print("  - tool dispatch + loop-back until a final answer")
    print("  - termination policy and step limits")
    print("  - system-prompt injection and middleware hooks")
    print("  - ToolRuntime injection (state/context/store) into tools")
    print("  - streaming + checkpointing hooks (AI-2)")
    print("  Both loops produced the SAME answer here — the difference is that")
    print("  the manual loop is yours to own and debug, while create_agent is")
    print("  a maintained harness with versioned behavior.")
    print("  ICE uses create_agent in production; the manual loop lives only as")
    print("  a learning comparison here.")


if __name__ == "__main__":
    main()
