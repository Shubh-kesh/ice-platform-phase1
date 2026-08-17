"""LEARNING ONLY — never imported by app/, no network, no DB.

CONTEXT vs STATE vs STORE:

  CONTEXT (ActorContext)  who is calling NOW — immutable, per-invocation.
  STATE   (checkpointer)  what happened in THIS THREAD — messages/thread.
  STORE   (InMemoryStore) longer-lived process-local data ACROSS threads.

Harmless example: a user's preferred report format. Thread A stores it, Thread
B for the SAME user retrieves it — but a DIFFERENT user must NOT. Namespaced by
user id in the store namespace, exactly like threads.

Limitations: InMemoryStore is PROCESS-LOCAL (like InMemorySaver) — it does not
survive restart and is not shared across workers. Never used for
authorization (that stays in ActorContext -> ToolRuntime.context).

Run:  python3 inmemory_store_demo.py
"""
from __future__ import annotations

import asyncio
import uuid

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore


class FakeModel(BaseChatModel):
    responses: list[AIMessage]

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        m = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=m)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fake-store"


USER_ALICE = str(uuid.uuid4())
USER_BOB = str(uuid.uuid4())

# A SINGLE process-local store shared across every agent/thread in this demo —
# exactly like the InMemorySaver checkpointer singleton in the app.
SHARED_STORE = InMemoryStore()


@tool
def set_report_format(format_name: str, runtime=None) -> str:
    """Store a preferred report format (namespaced by the caller's user id)."""
    ns = ("prefs", f"user:{runtime.context.user_id}")
    runtime.store.put(ns, "report_format", {"format": format_name})
    return f"stored {format_name}"


@tool
def get_report_format(runtime=None) -> str:
    """Read the caller's preferred report format from the store."""
    ns = ("prefs", f"user:{runtime.context.user_id}")
    item = runtime.store.get(ns, "report_format")
    return f"preferred format = {item.value['format'] if item else None}"


def _tc(name, args=None):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": f"call-{uuid.uuid4().hex[:6]}", "type": "tool_call"}])


def _agent(model):
    return create_agent(
        model=FakeModel(responses=model),
        tools=[set_report_format, get_report_format],
        checkpointer=InMemorySaver(),  # STATE (thread-scoped)
        store=SHARED_STORE,  # STORE (cross-thread, in-process)
    )


def _run(agent, user_id, thread, text):
    cfg = {"configurable": {"thread_id": f"{user_id}::{thread}"}}
    return asyncio.run(agent.ainvoke({"messages": [("user", text)]}, cfg, context=type("C", (), {"user_id": user_id})()))


def main() -> None:
    print("=" * 74)
    print("CONTEXT = who is calling NOW | STATE = this thread | STORE = across threads")
    print("=" * 74)

    # Thread A (Alice) stores her preference.
    agent_a = _agent([_tc("set_report_format", {"format_name": "concise"})])
    _run(agent_a, USER_ALICE, "thread-a", "I prefer concise reports")
    print("[STORE ] Alice set preferred format in thread A")

    # Thread B (Alice) retrieves it — same user, different thread.
    agent_b = _agent([_tc("get_report_format"), AIMessage(content="reads")])
    out = _run(agent_b, USER_ALICE, "thread-b", "what format do I prefer?")
    tool_msg = [m for m in out["messages"] if m.type == "tool"][-1].content
    print(f"[STORE ] Alice in thread B reads: {tool_msg}")

    # Bob must NOT see Alice's preference.
    agent_c = _agent([_tc("get_report_format"), AIMessage(content="reads")])
    out = _run(agent_c, USER_BOB, "thread-b", "what format do I prefer?")
    tool_msg = [m for m in out["messages"] if m.type == "tool"][-1].content
    print(f"[STORE ] Bob (same thread id!) reads: {tool_msg}")

    print()
    print("STATE  : thread B is a fresh conversation (no messages from A).")
    print("STORE  : Alice's preference survives across her threads, hidden from Bob.")
    print("CONTEXT: each call passes the caller's identity via ToolRuntime.context.")
    print("LIMIT  : InMemoryStore is PROCESS-LOCAL (resets on restart, per-worker).")
    print("        The store is NEVER used for authorization.")


if __name__ == "__main__":
    main()
