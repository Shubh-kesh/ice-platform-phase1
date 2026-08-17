"""LEARNING / SIMULATION ONLY — never imported by app/, no network, no DB.

LLMToolEmulator lets an agent exercise a SENSITIVE mutating tool's decision
path (tool selection, arguments, downstream response) WITHOUT executing the
real mutation. Here we emulate `receive_purchase_order` — a tool ICE has NOT
enabled — so the agent believes it exists and receives a SYNTHETIC plausible
result while the real function is never invoked (executions == 0).

CLEARLY LABELLED: nothing below writes ICE data. The emulated tool is NOT
available as a real production mutation.

Run:  python3 llm_tool_emulator_demo.py
"""
from __future__ import annotations

import asyncio
import uuid

from langchain.agents import create_agent
from langchain.agents.middleware import LLMToolEmulator
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

executions: list[dict] = []


@tool
def receive_purchase_order(project_id: str, po_number: str, quantity_received: int) -> str:
    """(SIMULATION ONLY) Record receipt of a purchase order line."""
    executions.append({"project_id": project_id, "po_number": po_number, "qty": quantity_received})
    return f"REAL receipt recorded for {po_number}"


class FakeModel(BaseChatModel):
    """Self-contained deterministic model (lab-only)."""

    responses: list[AIMessage]

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fake-emulator"


def tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{uuid.uuid4().hex[:6]}", "type": "tool_call"}])


def main() -> None:
    # Main model proposes receive_purchase_order; the EMULATOR model supplies
    # the synthetic result text.
    main_model = FakeModel(
        responses=[
            tool_call("receive_purchase_order", {"project_id": "PRJ-2026-0001", "po_number": "PO-1042", "quantity_received": 40}),
            AIMessage(content="I would record PO-1042 as received (40 units)."),
        ]
    )
    emulator_model = FakeModel(
        responses=[AIMessage(content='{"ok": true, "po_number": "PO-1042", "received": 40, "simulated": true}')]
    )

    agent = create_agent(
        model=main_model,
        tools=[receive_purchase_order],
        system_prompt="You are a procurement assistant (LEARNING SIMULATION ONLY).",
        middleware=[
            LLMToolEmulator(
                tools=["receive_purchase_order"],
                model=emulator_model,  # never a real provider here
            )
        ],
    )

    print("=" * 74)
    print("LEARNING / SIMULATION ONLY — no ICE data is written")
    print("=" * 74)
    out = asyncio.run(agent.ainvoke({"messages": [("user", "PO-1042 arrived — record 40 units received")]}))

    print("[tool selection] receive_purchase_order (argued by the main model)")
    print(f"[synthetic result] {out['messages'][-2].content!r}")  # emulator's ToolMessage
    print(f"[final response  ] {out['messages'][-1].content!r}")
    print(f"[real executions ] {len(executions)} (the real function never ran)")
    print()
    print("Why emulate BEFORE enabling: the agent's decision path (does it pick")
    print("the tool? what args? what does it say next?) is validated with zero")
    print("risk. Only after the path looks correct do we consider wiring the real,")
    print("HITL-protected tool.")


if __name__ == "__main__":
    main()
