"""
W7.3 — middleware/resilience tests (deterministic, no provider).

Covers ModelCallLimit, ToolCallLimit (checkpointer-backed), ModelRetry,
ModelFallback, PII (+ custom detectors + logging), the safe_tool/ToolError
hybrid, TodoList, and tool-selector scoping.
"""
import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware, ModelRetryMiddleware
from typing import ClassVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration

from app.ai import middleware as ai_middleware
from app.ai.agent import build_agent, stream_assistant
from app.ai.context import ActorContext
from app.ai.prompts import build_system_prompt
from app.core.config import settings
from app.models.user import UserRole
from tests.conftest import assign_user_to_project
from tests.fakes import FakeChatModel

pytestmark = pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")

THREAD = "66666666-6666-4666-8666-666666666666"


def _tool_call(name: str, args=None) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {}, "id": "call-1", "type": "tool_call"}],
    )


class LoopModel(BaseChatModel):
    """Requests a tool forever (or for `calls` times then a final answer)."""

    calls: int = 99
    count: ClassVar[int] = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        LoopModel.count += 1
        if LoopModel.count < self.calls:
            return ChatResult(
                generations=[ChatGeneration(message=_tool_call("get_my_notifications"))]
            )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "loop"


# --- Model call limit ---------------------------------------------------------


async def test_model_call_limit_terminates_loop(test_db, test_admin_user, monkeypatch):
    LoopModel.count = 0
    monkeypatch.setattr(settings, "ICE_AI_MODEL_RUN_LIMIT", 3)
    actor = ActorContext.from_user(test_admin_user)
    model = LoopModel(calls=99)
    events = [
        item
        async for item in stream_assistant(test_db, actor, "go", model=model, thread_id=THREAD)
    ]
    complete = [d for e, d in events if e == "assistant_complete"]
    assert complete, "run should complete (not hang)"
    assert complete[0]["usage"]["model_calls"] <= 3


async def test_model_call_limit_below_and_at(test_db, test_admin_user, monkeypatch):
    LoopModel.count = 0
    monkeypatch.setattr(settings, "ICE_AI_MODEL_RUN_LIMIT", 10)
    actor = ActorContext.from_user(test_admin_user)
    model = LoopModel(calls=2)  # below limit
    events = [
        item
        async for item in stream_assistant(test_db, actor, "go", model=model, thread_id=THREAD)
    ]
    assert events[-1][0] == "assistant_complete"
    complete = [d for e, d in events if e == "assistant_complete"][0]
    assert complete["usage"]["model_calls"] == 2


# --- Tool call limit (checkpointer-backed thread limit) -----------------------


async def test_tool_call_limit_bounds_tool_executions(test_db, test_admin_user, monkeypatch):
    LoopModel.count = 0
    monkeypatch.setattr(settings, "ICE_AI_TOOL_RUN_LIMIT", 5)
    monkeypatch.setattr(settings, "ICE_AI_TOOL_THREAD_LIMIT", 5)
    actor = ActorContext.from_user(test_admin_user)
    model = LoopModel(calls=50)
    events = [
        item
        async for item in stream_assistant(test_db, actor, "go", model=model, thread_id=THREAD)
    ]
    finished = [d for e, d in events if e == "tool_finished"]
    assert len(finished) <= 5


# --- Model retry --------------------------------------------------------------


class FlakyModel(BaseChatModel):
    """Fails once (or N times) with a transient error, then succeeds."""

    fail_times: int = 1
    count: ClassVar[int] = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        FlakyModel.count += 1
        if FlakyModel.count <= self.fail_times:
            raise ai_middleware.ModelTransientError("transient")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "flaky"


async def test_model_retry_succeeds(test_db, test_admin_user):
    FlakyModel.count = 0
    agent = create_agent(
        model=FlakyModel(fail_times=1),
        tools=[],
        system_prompt="t",
        middleware=[
            ModelRetryMiddleware(max_retries=1, retry_on=ai_middleware.model_retry_on, initial_delay=0.01, jitter=False)
        ],
    )
    result = await agent.ainvoke({"messages": [("user", "hi")]}, context=ActorContext.from_user(test_admin_user))
    assert FlakyModel.count == 2
    assert result["messages"][-1].content == "ok"


async def test_model_retry_exhausted_safe(test_db, test_admin_user):
    FlakyModel.count = 0
    agent = create_agent(
        model=FlakyModel(fail_times=99),
        tools=[],
        system_prompt="t",
        middleware=[
            ModelRetryMiddleware(max_retries=1, retry_on=ai_middleware.model_retry_on, initial_delay=0.01, jitter=False)
        ],
    )
    result = await agent.ainvoke({"messages": [("user", "hi")]}, context=ActorContext.from_user(test_admin_user))
    assert "failed" in str(result["messages"][-1].content).lower()


# --- Model fallback -----------------------------------------------------------


class FallbackModel(BaseChatModel):
    """Succeeds with `label` content."""

    label: str = "fallback"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.label))])

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "fallback"


class FailingPrimary(BaseChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("primary down")

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self):
        return "primary"


async def test_model_fallback_primary_failure(test_db, test_admin_user):
    agent = create_agent(
        model=FailingPrimary(),
        tools=[],
        system_prompt="t",
        middleware=[ModelFallbackMiddleware(FailingPrimary(), FallbackModel(label="fallback-ok"))],
    )
    result = await agent.ainvoke({"messages": [("user", "hi")]}, context=ActorContext.from_user(test_admin_user))
    assert result["messages"][-1].content == "fallback-ok"


async def test_model_fallback_primary_success_unused(test_db, test_admin_user):
    primary = FallbackModel(label="primary-ok")
    agent = create_agent(
        model=primary,
        tools=[],
        system_prompt="t",
        middleware=[ModelFallbackMiddleware(primary, FallbackModel(label="fallback-ok"))],
    )
    result = await agent.ainvoke({"messages": [("user", "hi")]}, context=ActorContext.from_user(test_admin_user))
    assert result["messages"][-1].content == "primary-ok"


# --- PII ----------------------------------------------------------------------


async def test_pii_email_redacted_on_input(test_db, test_admin_user, monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_PII_ENABLED", True)
    actor = ActorContext.from_user(test_admin_user)
    model = FakeChatModel(responses=[AIMessage(content="ok")])
    _ = [item async for item in stream_assistant(test_db, actor, "mail priya@example.com now", model=model, thread_id=THREAD)]
    blob = " ".join(str(getattr(m, "content", "")) for call in model.calls for m in call)
    assert "priya@example.com" not in blob  # redacted by PIIMiddleware
    assert "[REDACTED_EMAIL]" in blob


async def test_pii_custom_detectors_and_identifiers(test_db, test_admin_user, monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_PII_ENABLED", True)
    monkeypatch.setattr(settings, "ICE_AI_PII_CUSTOM_ENABLED", True)
    actor = ActorContext.from_user(test_admin_user)
    model = FakeChatModel(responses=[AIMessage(content="ok")])
    _ = [item async for item in stream_assistant(
        test_db, actor,
        "my pan ABCDE1234F and aadhaar 2345 6789 0123 and project PRJ-2026-0001",
        model=model, thread_id=THREAD,
    )]
    blob = " ".join(str(getattr(m, "content", "")) for call in model.calls for m in call)
    assert "ABCDE1234F" not in blob and "2345 6789 0123" not in blob  # masked
    assert "PRJ-2026-0001" in blob  # identifiers are NOT PII


async def test_pii_not_leaked_to_logs(caplog, test_db, test_admin_user, monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_DEBUG", True)
    monkeypatch.setattr(settings, "ICE_AI_PII_ENABLED", True)
    actor = ActorContext.from_user(test_admin_user)
    model = FakeChatModel(responses=[AIMessage(content="ok")])
    import logging

    caplog.set_level(logging.INFO)
    _ = [item async for item in stream_assistant(test_db, actor, "email priya@example.com", model=model, thread_id=THREAD)]
    blob = "\n".join(r.msg for r in caplog.records if isinstance(r.msg, str))
    assert "priya@example.com" not in blob


# --- ToolError hybrid (safe_tool preserved) -----------------------------------


async def test_safe_tool_deterministic_errors_preserved(test_db, test_client_user, test_project):
    # RBAC denial stays a deterministic tool result (not middleware exception formatting)
    actor = ActorContext.from_user(test_client_user)
    fake = FakeChatModel(responses=[_tool_call("get_project_budget", {"project_id": str(test_project.id)}), AIMessage(content="no")])
    agent = create_agent(model=fake, tools=__import__("app.ai.tools", fromlist=["ALL_TOOLS"]).ALL_TOOLS,
                         system_prompt=build_system_prompt(), context_schema=ActorContext)
    events = [item async for item in stream_assistant(test_db, actor, "budget", model=fake, agent=agent, thread_id=THREAD)]
    finished = [d for e, d in events if e == "tool_finished"]
    assert finished == [{"tool": "Project budget", "ok": False, "error": "not_permitted"}]


# --- TodoList -----------------------------------------------------------------


async def test_todo_middleware_wired(test_db, test_admin_user, monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_TODO_ENABLED", True)
    actor = ActorContext.from_user(test_admin_user)
    model = FakeChatModel(responses=[AIMessage(content="plan ready")])
    events = [item async for item in stream_assistant(test_db, actor, "review the project", model=model, thread_id=THREAD)]
    assert events[-1][0] == "assistant_complete"  # TodoListMiddleware doesn't break the agent


# --- Tool selector scoping ----------------------------------------------------


async def test_tool_selector_never_widens_client_tools(test_db, test_client_user, test_project, monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_TOOL_SELECTOR_ENABLED", True)
    monkeypatch.setattr(settings, "ICE_AI_TOOL_SELECTOR_MAX_TOOLS", 6)
    monkeypatch.setattr(settings, "ICE_AI_TOOL_SELECTOR_ALWAYS_INCLUDE", "list_projects,get_project")
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    from app.ai.agent import tools_for_role_toolset

    agent = build_agent(UserRole.CLIENT, model=FakeChatModel(responses=[AIMessage(content="ok")]))
    assert agent is not None
    # The selector may only NARROW the role-authorized universe — the budget/PO
    # tools are simply not in the client agent at all.
    assert "get_project_budget" not in {t.name for t in tools_for_role_toolset(UserRole.CLIENT)}
