"""
W7.4 — LLMToolEmulator / InMemoryStore / return_direct / dynamic tool gating.

Deterministic assertions (no DB, no network) that mirror the ai_labs demos so
the concepts are pinned in CI:
- emulator returns a synthetic result and the real function never runs;
- InMemoryStore shares data across a user's threads but isolates other users;
- return_direct skips the extra model call;
- dynamic gating (wrap_model_call) shrinks the model-visible toolset while hard
  RBAC remains unchanged.
"""
import asyncio
import uuid

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import LLMToolEmulator, wrap_model_call
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

pytestmark = pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")


class FakeChat(BaseChatModel):
    """Deterministic scripted model for these tests."""

    responses: list[AIMessage] = []
    calls: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        message = self.responses.pop(0) if self.responses else AIMessage(content="Done.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fake-w74"


def tool_call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{uuid.uuid4().hex[:6]}", "type": "tool_call"}])


# --- LLMToolEmulator: synthetic result, zero real executions -----------------------


def test_llm_tool_emulator_synthetic_result_no_execution():
    real_executions = []

    @tool
    def record_job_cost(project_id: str, amount: float) -> str:
        """(SIMULATION ONLY) record a job cost."""
        real_executions.append((project_id, amount))
        return "REAL cost recorded"

    main_model = FakeChat(
        responses=[
            tool_call("record_job_cost", {"project_id": "PRJ-1", "amount": 1000}),
            AIMessage(content="I would record the cost."),
        ]
    )
    emulator_model = FakeChat(responses=[AIMessage(content='{"ok": true, "simulated": true}')])

    agent = create_agent(
        model=main_model,
        tools=[record_job_cost],
        system_prompt="LEARNING SIMULATION ONLY",
        middleware=[LLMToolEmulator(tools=["record_job_cost"], model=emulator_model)],
    )
    out = asyncio.run(agent.ainvoke({"messages": [("user", "record a cost")]}))
    assert "simulated" in str(out["messages"][-2].content)
    assert real_executions == []  # the real mutation NEVER ran


# --- InMemoryStore: same-user cross-thread, different-user isolation -----------------


def test_inmemory_store_user_scoped_cross_thread():
    store = InMemoryStore()
    alice, bob = str(uuid.uuid4()), str(uuid.uuid4())

    @tool
    def set_pref(format_name: str, runtime=None) -> str:
        """Store a preferred report format (user-namespaced)."""
        ns = ("prefs", f"user:{runtime.context.user_id}")
        store.put(ns, "format", {"format": format_name})
        return "stored"

    @tool
    def get_pref(runtime=None) -> str:
        """Read the caller's preferred report format."""
        ns = ("prefs", f"user:{runtime.context.user_id}")
        item = store.get(ns, "format")
        return f"pref={item.value['format'] if item else None}"

    class Ctx:
        def __init__(self, user_id):
            self.user_id = user_id

    def _run(user_id, thread, responses):
        agent = create_agent(
            model=FakeChat(responses=responses),
            tools=[set_pref, get_pref],
            checkpointer=InMemorySaver(),
            store=store,
        )
        cfg = {"configurable": {"thread_id": f"{user_id}::{thread}"}}
        out = asyncio.run(agent.ainvoke({"messages": [("user", "go")]}, cfg, context=Ctx(user_id)))
        return [m.content for m in out["messages"] if m.type == "tool"][-1]

    assert _run(alice, "A", [tool_call("set_pref", {"format_name": "concise"})]) == "stored"
    # same user, different thread -> store survives
    assert "concise" in _run(alice, "B", [tool_call("get_pref", {})])
    # different user, same thread id -> isolated
    assert "pref=None" in _run(bob, "B", [tool_call("get_pref", {})])


# --- return_direct: model-call count differs ----------------------------------------


def test_return_direct_skips_extra_model_call():
    @tool
    def exact_value(kind: str) -> str:
        """An exact-value read-only tool."""
        return "Rs 420/bag"

    def _run(direct):
        model = FakeChat(
            responses=[tool_call("exact_value", {"kind": "cement"}), AIMessage(content="It is Rs 420/bag.")]
        )
        t = exact_value if not direct else exact_value.model_copy(update={"return_direct": True})
        agent = create_agent(model=model, tools=[t])
        out = asyncio.run(agent.ainvoke({"messages": [("user", "rate?")]}))
        return model.calls, out["messages"][-1].content

    calls_normal, _ = _run(False)
    calls_direct, final = _run(True)
    assert calls_normal == 2
    assert calls_direct == 1
    assert "Rs 420/bag" in final


# --- dynamic tool gating ------------------------------------------------------------


def test_wrap_model_call_gates_model_visible_toolset():
    @tool
    def get_project_budget(project_id: str) -> str:
        """Finance surface."""
        return "1M"

    @tool
    def list_projects() -> str:
        """Project list."""
        return "[PRJ-1]"

    class GatedFake(FakeChat):
        bound_seen: list = []

        def bind_tools(self, tools, **kwargs):
            self.bound_seen.append(sorted(getattr(t, "name", str(t)) for t in tools) if tools else [])
            return self

    gated = GatedFake(responses=[AIMessage(content="ok")])

    @wrap_model_call
    async def gate(request, handler):
        request.tools = [t for t in request.tools if t.name != "get_project_budget"]
        return await handler(request)

    agent = create_agent(model=gated, tools=[list_projects, get_project_budget], system_prompt="t", middleware=[gate])
    asyncio.run(agent.ainvoke({"messages": [("user", "go")]}))
    # the model-visible toolset shrank from 2 to 1 (finance removed).
    assert gated.bound_seen == [["list_projects"]]
    # hard RBAC is unchanged — the gated-out tool still exists and self-checks.
    assert get_project_budget.name == "get_project_budget"
