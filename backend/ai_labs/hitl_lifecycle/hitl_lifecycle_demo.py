"""LEARNING ONLY — never imported by app/, no network, no DB.

Human-in-the-loop lifecycle: the agent PROPOSES a mutating tool call, the
HumanInTheLoopMiddleware interrupts, the human decides (approve / edit / reject
/ respond), and Command(resume=...) continues the graph. This demo shows the
OBSERVABLE lifecycle — AIMessage(tool call) -> interrupt -> checkpoint state ->
Command(resume) -> ToolMessage -> final AIMessage — with a deterministic fake
model and a simulated mutating tool (no ICE data touched).

Run:  python3 hitl_lifecycle_demo.py
"""
from __future__ import annotations

import asyncio
import uuid

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


class FakeChatModel(BaseChatModel):
    """Self-contained deterministic scripted model (lab-only)."""

    responses: list[AIMessage]

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fake-hitl"


executed: list[dict] = []


@tool
def receive_purchase_order(po_number: str) -> str:
    """Simulated mutating action (LEARNING ONLY — does not touch ICE data)."""
    executed.append({"po_number": po_number})
    return f"PO {po_number} received"


def tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{uuid.uuid4().hex[:6]}", "type": "tool_call"}])


def build(responses: list[AIMessage]):
    return create_agent(
        model=FakeChatModel(responses=responses),
        tools=[receive_purchase_order],
        checkpointer=InMemorySaver(),
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on={"receive_purchase_order": {"allowed_decisions": ["approve", "edit", "reject", "respond"], "description": "Approve receiving this PO"}}
            )
        ],
    )


def run_lifecycle(label: str, decision: dict, responses: list[AIMessage]) -> None:
    agent = build(responses)
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}

    print(f"\n{'=' * 74}\n{label}\n{'=' * 74}")
    # 1) model proposes a tool call -> HITL interrupts
    out = asyncio.run(agent.ainvoke({"messages": [("user", "receive PO 47")]}, cfg))
    interrupt = out.get("__interrupt__")
    if interrupt:
        value = interrupt[0].value
        req = value["action_requests"][0]
        print(f"[AIMessage] proposed tool: {req['name']} args={req['args']}")
        print(f"[interrupt ] description: {req['description']} | decisions: {value['review_configs'][0]['allowed_decisions']}")
    state = asyncio.run(agent.aget_state(cfg))
    print(f"[checkpoint] next={state.next} interrupts={len(state.interrupts)}")
    before = len(executed)

    # 2) human decision -> Command(resume=...)
    resumed = asyncio.run(agent.ainvoke(Command(resume={"decisions": [decision]}), cfg))

    # 3) observable aftermath
    tool_msgs = [m for m in resumed["messages"] if isinstance(m, ToolMessage)]
    final = resumed["messages"][-1]
    ran = len(executed) - before
    for tm in tool_msgs:
        print(f"[ToolMessage] content={tm.content!r} status={getattr(tm, 'status', '?')}")
    print(f"[AIMessage  ] final: {final.content!r}")
    print(f"[observable ] tool executed={ran} times | executed={executed[-ran:] if ran else []}")


def main() -> None:
    run_lifecycle("APPROVE — original args run", {"type": "approve"}, [tool_call("receive_purchase_order", {"po_number": "PO-001"}), AIMessage(content="PO-001 received")])
    run_lifecycle("EDIT — args replaced before execution", {"type": "edit", "edited_action": {"name": "receive_purchase_order", "args": {"po_number": "PO-002"}}}, [tool_call("receive_purchase_order", {"po_number": "PO-001"}), AIMessage(content="PO-002 received")])
    run_lifecycle("REJECT — never executes", {"type": "reject", "message": "Wrong PO"}, [tool_call("receive_purchase_order", {"po_number": "PO-003"}), AIMessage(content="ok")])
    run_lifecycle("RESPOND — human answers for the tool", {"type": "respond", "message": "PO already in system"}, [tool_call("receive_purchase_order", {"po_number": "PO-004"}), AIMessage(content="ok")])


if __name__ == "__main__":
    main()
