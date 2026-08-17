"""
AI-1.1 — ICE Copilot foundation + core tools + security tests.

All tests run against real Postgres (test_db fixture) with a deterministic
fake chat model or direct tool calls — no live OpenAI key, no network. Tools
are exercised both directly (fabricated ToolRuntime + bound session) and
through a create_agent harness.
"""
import uuid
import warnings
from datetime import date

import pytest
from langchain.agents import create_agent
from langchain.tools import ToolRuntime, tool as lc_tool
from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from app.ai.agent import (
    AssistantNotConfigured,
    _provider_api_key,
    build_agent,
    build_model,
    run_agent,
    tools_for_role_toolset,
)
from app.ai.context import ActorContext, session_scope
from app.ai.security import (
    TOOL_WEB_SEARCH,
    TOOL_GET_PROJECT_TASKS,
    TOOL_GET_DAILY_SITE_LOGS,
    TOOL_GET_INVOICES,
    TOOL_GET_JOB_COSTS,
    TOOL_GET_PO_DELIVERIES,
    TOOL_GET_BILLING_MILESTONES,
    TOOL_GET_INVENTORY_MOVEMENTS,
    TOOL_GET_MY_NOTIFICATIONS,
    TOOL_GET_PROJECT,
    TOOL_GET_PROJECT_BUDGET,
    TOOL_GET_PROJECT_HEALTH,
    TOOL_GET_PROJECT_INVENTORY,
    TOOL_GET_PURCHASE_ORDERS,
    TOOL_LIST_PROJECTS,
    TOOL_CREATE_TASK,
    TOOL_CREATE_DAILY_SITE_LOG,
    ToolForbidden,
    assert_tool_allowed,
    tools_for_role,
)
from app.ai.tools import ALL_TOOLS, TOOL_BY_NAME
from app.ai.tools.base import bound_items, require_role
from app.ai.tools.finance import get_project_budget
from app.ai.tools.health import get_project_health
from app.ai.tools.inventory import get_project_inventory
from app.ai.tools.notifications import get_my_notifications
from app.ai.tools.procurement import get_purchase_orders
from app.ai.tools.projects import get_project, list_projects
from app.core.config import settings
from app.models.inventory import InventoryItem
from app.models.notification import Notification
from app.models.project import Project, ProjectStatus
from app.models.purchase_order import POLine, POStatus, PurchaseOrder
from app.models.user import User, UserRole
from app.models.vendor import Vendor
from tests.conftest import assign_user_to_project
from tests.fakes import FakeChatModel

EXPECTED_SEVEN = frozenset(
    {
        TOOL_LIST_PROJECTS,
        TOOL_GET_PROJECT,
        TOOL_GET_PROJECT_HEALTH,
        TOOL_GET_PROJECT_BUDGET,
        TOOL_GET_PROJECT_INVENTORY,
        TOOL_GET_PURCHASE_ORDERS,
        TOOL_GET_MY_NOTIFICATIONS,
    }
)

EXPECTED_CATALOG = frozenset(
    {
        TOOL_LIST_PROJECTS,
        TOOL_GET_PROJECT,
        TOOL_GET_PROJECT_HEALTH,
        TOOL_GET_PROJECT_BUDGET,
        TOOL_GET_PROJECT_INVENTORY,
        TOOL_GET_PURCHASE_ORDERS,
        TOOL_GET_MY_NOTIFICATIONS,
        TOOL_WEB_SEARCH,
        TOOL_GET_PROJECT_TASKS,
        TOOL_GET_DAILY_SITE_LOGS,
        TOOL_GET_JOB_COSTS,
        TOOL_GET_PO_DELIVERIES,
        TOOL_GET_BILLING_MILESTONES,
        TOOL_GET_INVENTORY_MOVEMENTS,
        TOOL_GET_INVOICES,
        # W7.4 HITL-guarded mutations.
        TOOL_CREATE_TASK,
        TOOL_CREATE_DAILY_SITE_LOG,
    }
)

IDENTITY_ARG_NAMES = ("user_id", "role", "email", "project_access", "assignment", "runtime")


def make_runtime(actor: ActorContext) -> ToolRuntime:
    return ToolRuntime(
        state={},
        context=actor,
        config={},
        stream_writer=lambda *args, **kwargs: None,
        tool_call_id=None,
        store=None,
    )


def make_project(test_db, code: str, name: str) -> Project:
    project = Project(
        project_code=code,
        name=name,
        site_address="123 Test Street",
        client_name="Test Client Co.",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        budget_total=1000000,
    )
    test_db.add(project)
    return project


async def _add_inventory_item(db, project_id, name="Cement", qty=100) -> InventoryItem:
    item = InventoryItem(
        project_id=project_id,
        name=name,
        unit="bag",
        quantity_on_hand=qty,
        reorder_threshold=20,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _add_vendor_and_po(db, project_id) -> tuple[Vendor, PurchaseOrder]:
    vendor = Vendor(name=f"Vendor {uuid.uuid4().hex[:8]}")
    db.add(vendor)
    await db.commit()
    await db.refresh(vendor)
    po = PurchaseOrder(
        po_number=f"PO-TEST-{uuid.uuid4().hex[:6]}",
        project_id=project_id,
        vendor_id=vendor.id,
        status=POStatus.APPROVED,
        order_date=date.today(),
        total_amount=1200,
        created_by=None,
    )
    db.add(po)
    await db.commit()
    await db.refresh(po)
    db.add(
        POLine(
            purchase_order_id=po.id,
            description="Cement",
            quantity=100,
            unit="bag",
            unit_price=12,
            cost_code="material",
        )
    )
    await db.commit()
    return vendor, po


async def _call(tool, user, db, **kwargs):
    ctx = ActorContext.from_user(user)
    async with session_scope(db):
        return await tool.coroutine(runtime=make_runtime(ctx), **kwargs)


# --- ActorContext ----------------------------------------------------------------


def _transient_user(role: UserRole) -> "User":
    """A non-persisted User for pure unit tests (no DB fixture needed)."""
    return User(
        id=uuid.uuid4(),
        email=f"{role.value}@test.com",
        full_name="Unit User",
        role=role,
        hashed_password="x",
    )


def test_actor_context_from_user():
    user = _transient_user(UserRole.ADMIN)
    ctx = ActorContext.from_user(user)
    assert ctx.user_id == user.id
    assert ctx.role == UserRole.ADMIN


def test_actor_context_is_immutable():
    ctx = ActorContext.from_user(_transient_user(UserRole.ADMIN))
    with pytest.raises(Exception):
        ctx.user_id = uuid.uuid4()


# --- Tool registry + schemas ------------------------------------------------------


def test_tool_catalog():
    assert set(TOOL_BY_NAME.keys()) == EXPECTED_CATALOG
    assert len(ALL_TOOLS) == 17


def test_no_generic_sql_or_query_tool():
    for name in TOOL_BY_NAME:
        assert "sql" not in name.lower()
        assert "query" not in name.lower()
        assert "execute" not in name.lower()


def test_tool_schemas_hide_identity_and_runtime():
    """The model-facing schema of every tool exposes only domain arguments."""
    for name, tool in TOOL_BY_NAME.items():
        props = set(tool.args.keys())
        for forbidden in IDENTITY_ARG_NAMES:
            assert forbidden not in props, f"{name} leaks {forbidden}"


async def test_forged_identity_argument_cannot_escalate(test_db, test_client_user, test_project):
    """Identity is never accepted from arguments: forged user_id/role kwargs are
    not part of the tool contract and are rejected (never honored), so a client
    still cannot obtain project detail they are not entitled to."""
    ctx = ActorContext.from_user(test_client_user)
    async with session_scope(test_db):
        res = await get_project.coroutine(
            project_id=test_project.id,
            user_id=uuid.uuid4(),
            role="admin",
            runtime=make_runtime(ctx),
        )
    assert res.get("error") is not None  # forged args rejected/ignored — never escalated
    assert "project_code" not in res


# --- Defense-in-depth allow-list ----------------------------------------------------


def test_role_tool_menus():
    assert tools_for_role(UserRole.ADMIN) == EXPECTED_CATALOG
    # W7.4: procurement mirrors REST write roles — no schedule/site-log writes.
    assert tools_for_role(UserRole.PROCUREMENT_MANAGER) == EXPECTED_CATALOG - {
        TOOL_CREATE_TASK,
        TOOL_CREATE_DAILY_SITE_LOG,
    }
    assert tools_for_role(UserRole.SITE_SUPERVISOR) == frozenset(
        {
            TOOL_LIST_PROJECTS,
            TOOL_GET_PROJECT,
            TOOL_GET_PROJECT_HEALTH,
            TOOL_GET_PROJECT_INVENTORY,
            TOOL_GET_INVENTORY_MOVEMENTS,
            TOOL_GET_PROJECT_TASKS,
            TOOL_GET_DAILY_SITE_LOGS,
            TOOL_GET_MY_NOTIFICATIONS,
            TOOL_WEB_SEARCH,
            TOOL_CREATE_TASK,
            TOOL_CREATE_DAILY_SITE_LOG,
        }
    )
    assert tools_for_role(UserRole.CLIENT) == frozenset(
        {
            TOOL_LIST_PROJECTS,
            TOOL_GET_PROJECT,
            TOOL_GET_PROJECT_TASKS,
            TOOL_GET_DAILY_SITE_LOGS,
            TOOL_GET_INVOICES,
            TOOL_GET_MY_NOTIFICATIONS,
            TOOL_WEB_SEARCH,
        }
    )


def test_assert_tool_allowed_denies():
    with pytest.raises(ToolForbidden):
        assert_tool_allowed(UserRole.CLIENT, TOOL_GET_PROJECT_BUDGET)


def test_require_role_raises_forbidden():
    ctx = ActorContext.from_user(_transient_user(UserRole.CLIENT))
    with pytest.raises(ToolForbidden):
        require_role(ctx, UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)


# --- Direct tool behavior: allowed / forbidden per role ------------------------------


async def test_list_projects_admin_and_client(test_db, test_admin_user, test_client_user, test_project):
    admin_res = await _call(list_projects, test_admin_user, test_db)
    assert admin_res["total_count"] == 1
    (item,) = admin_res["items"]
    assert item["project_code"] == "PRJ-TEST-0001"
    assert "budget_total" in item  # admin/proc see money

    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    client_res = await _call(list_projects, test_client_user, test_db)
    assert client_res["total_count"] == 1
    (item,) = client_res["items"]
    assert "budget_total" not in item  # M6 client shape has no money
    assert "budget_spent" not in item


async def test_list_projects_client_scoped_to_assigned(test_db, test_client_user, test_project):
    second = make_project(test_db, "PRJ-TEST-0002", "Other")
    await test_db.commit()
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    res = await _call(list_projects, test_client_user, test_db)
    assert res["total_count"] == 1
    assert res["items"][0]["project_code"] == "PRJ-TEST-0001"
    assert second.project_code not in [i["project_code"] for i in res["items"]]


async def test_get_project_role_shapes(test_db, test_admin_user, test_supervisor_user, test_client_user, test_project):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    admin = await _call(get_project, test_admin_user, test_db, project_id=test_project.id)
    assert "budget_total" in admin and "site_address" in admin
    sup = await _call(get_project, test_supervisor_user, test_db, project_id=test_project.id)
    assert "budget_total" not in sup and "site_address" in sup
    client = await _call(get_project, test_client_user, test_db, project_id=test_project.id)
    assert "budget_total" not in client and "budget_spent" not in client
    assert "completed_at" in client  # client shape keeps schedule progress


async def test_unassigned_project_idor(test_db, test_client_user, test_supervisor_user, test_project):
    client_res = await _call(get_project, test_client_user, test_db, project_id=test_project.id)
    assert client_res["error"] == "not_permitted"
    sup_res = await _call(get_project, test_supervisor_user, test_db, project_id=test_project.id)
    assert sup_res["error"] == "not_permitted"


async def test_get_project_health_allowed_roles(test_db, test_admin_user, test_supervisor_user, test_client_user, test_project):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)

    admin = await _call(get_project_health, test_admin_user, test_db, project_id=test_project.id)
    assert admin["project_id"] == str(test_project.id)
    assert "overall" in admin and "timeline" in admin

    sup = await _call(get_project_health, test_supervisor_user, test_db, project_id=test_project.id)
    assert sup["project_id"] == str(test_project.id)  # supervisors keep health (M6)

    client = await _call(get_project_health, test_client_user, test_db, project_id=test_project.id)
    assert client["error"] == "not_permitted"  # M6: health denied to clients


async def test_get_project_budget_admin_only(test_db, test_admin_user, test_procurement_user, test_supervisor_user, test_client_user, test_project):
    admin = await _call(get_project_budget, test_admin_user, test_db, project_id=test_project.id)
    assert admin["budget_total"] == 1000000.0
    proc = await _call(get_project_budget, test_procurement_user, test_db, project_id=test_project.id)
    assert proc["budget_total"] == 1000000.0
    assert (await _call(get_project_budget, test_supervisor_user, test_db, project_id=test_project.id))["error"] == "not_permitted"
    assert (await _call(get_project_budget, test_client_user, test_db, project_id=test_project.id))["error"] == "not_permitted"


async def test_get_project_inventory_roles(test_db, test_admin_user, test_supervisor_user, test_client_user, test_project):
    item = await _add_inventory_item(test_db, test_project.id)
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)

    admin = await _call(get_project_inventory, test_admin_user, test_db, project_id=test_project.id)
    assert admin["items"][0]["item_id"] == str(item.id)
    assert admin["items"][0]["low_stock"] is False

    sup = await _call(get_project_inventory, test_supervisor_user, test_db, project_id=test_project.id)
    assert sup["items"][0]["name"] == "Cement"  # supervisor keeps REST read parity

    client = await _call(get_project_inventory, test_client_user, test_db, project_id=test_project.id)
    assert client["error"] == "not_permitted"


async def test_get_purchase_orders_admin_only(test_db, test_admin_user, test_client_user, test_project):
    _, po = await _add_vendor_and_po(test_db, test_project.id)

    admin = await _call(get_purchase_orders, test_admin_user, test_db, project_id=test_project.id)
    assert admin["items"][0]["po_id"] == str(po.id)
    assert admin["items"][0]["status"] == POStatus.APPROVED.value

    client = await _call(get_purchase_orders, test_client_user, test_db, project_id=test_project.id)
    assert client["error"] == "not_permitted"


async def test_get_my_notifications_ownership(test_db, test_admin_user, test_client_user):
    note = Notification(
        user_id=test_client_user.id,
        project_id=None,
        type="project_assigned",
        title="Assigned",
        body="You were assigned to a project",
        link="/projects/abc",
        read_at=None,
    )
    test_db.add(note)
    await test_db.commit()

    client = await _call(get_my_notifications, test_client_user, test_db)
    assert client["items"][0]["notification_id"] == str(note.id)
    assert client["items"][0]["read"] is False

    admin = await _call(get_my_notifications, test_admin_user, test_db)
    assert admin["items"] == []  # another user's notifications are never returned


# --- Output bounding ----------------------------------------------------------------


def test_bound_items_row_limit_and_truncation(monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_MAX_TOOL_RESULT_CHARS", 5000)
    items = [{"name": f"item-{i}"} for i in range(10)]
    res = bound_items(items, total_count=10, limit=3)
    assert res["returned_count"] == 3
    assert res["total_count"] == 10
    assert res["truncated"] is True


def test_bound_items_char_budget_never_splits_json(monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_MAX_TOOL_RESULT_CHARS", 60)
    items = [{"name": "a" * 40}, {"name": "b" * 40}, {"name": "c" * 40}]
    res = bound_items(items, total_count=3, limit=10)
    assert res["truncated"] is True
    assert res["returned_count"] < 3
    assert all(isinstance(i, dict) and "name" in i for i in res["items"])


# --- Safe error transformation -------------------------------------------------------


async def test_unexpected_failure_becomes_safe_internal_error(test_admin_user):
    """No DB session bound -> tools must fail safe, never leak internals."""
    ctx = ActorContext.from_user(test_admin_user)
    res = await list_projects.coroutine(runtime=make_runtime(ctx))  # no session_scope
    assert res["error"] == "internal"


# --- Model factory ----------------------------------------------------------------------


def test_model_factory_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_ENABLED", False)
    with pytest.raises(AssistantNotConfigured):
        build_model()


def test_model_factory_missing_key(monkeypatch):
    _set_provider(monkeypatch, "openai", key="")
    with pytest.raises(AssistantNotConfigured):
        build_model()


def test_model_factory_constructs_without_network(monkeypatch):
    _set_provider(monkeypatch, "openai", key="sk-test-dummy")
    model = build_model()
    assert model is not None  # construction performs no network call


def _set_provider(monkeypatch, provider: str, key: str = "sk-test"):
    monkeypatch.setattr(settings, "ICE_AI_ENABLED", True)
    monkeypatch.setattr(settings, "ICE_AI_PROVIDER", provider)
    monkeypatch.setattr(settings, "ICE_AI_API_KEY", "")
    for name in ("OPENAI", "ANTHROPIC", "GROQ", "OPENROUTER"):
        monkeypatch.setattr(settings, f"ICE_AI_{name}_API_KEY", "" if name.upper() != provider.upper() else key)


def test_model_factory_swappable_providers(monkeypatch):
    """Each supported provider builds its model type without network calls."""
    expected = {
        "openai": "ChatOpenAI",
        "anthropic": "ChatAnthropic",
        "groq": "ChatGroq",
        "openrouter": "ChatOpenAI",  # OpenAI-compatible path via base_url
    }
    for provider, class_name in expected.items():
        _set_provider(monkeypatch, provider)
        model = build_model()
        assert type(model).__name__ == class_name, provider


def test_model_factory_provider_key_precedence(monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_PROVIDER", "openai")
    monkeypatch.setattr(settings, "ICE_AI_API_KEY", "generic-key")
    monkeypatch.setattr(settings, "ICE_AI_OPENAI_API_KEY", "specific-key")
    assert _provider_api_key("openai") == "specific-key"
    monkeypatch.setattr(settings, "ICE_AI_OPENAI_API_KEY", "")
    assert _provider_api_key("openai") == "generic-key"


def test_model_factory_missing_provider_key(monkeypatch):
    _set_provider(monkeypatch, "anthropic", key="")
    with pytest.raises(AssistantNotConfigured):
        build_model()


def test_model_factory_missing_provider(monkeypatch):
    monkeypatch.setattr(settings, "ICE_AI_ENABLED", True)
    monkeypatch.setattr(settings, "ICE_AI_PROVIDER", "")
    monkeypatch.setattr(settings, "ICE_AI_API_KEY", "sk-test")
    with pytest.raises(AssistantNotConfigured):
        build_model()


# --- Agent-level tests (fake model, real harness) -----------------------------------------


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
async def test_agent_routes_to_tool_and_returns_grounded_answer(test_db, test_admin_user, test_project):
    model = FakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_project_health",
                        "args": {"project_id": str(test_project.id)},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="The project is on track overall."),
        ]
    )
    agent = build_agent(UserRole.ADMIN, model=model)
    ctx = ActorContext.from_user(test_admin_user)
    result = await run_agent(agent, [("user", "why is this project unhealthy?")], ctx, test_db)
    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert tool_msgs, "agent should have called get_project_health"
    assert '"overall"' in str(tool_msgs[0].content)
    assert result["messages"][-1].content == "The project is on track overall."


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
async def test_agent_read_only_no_mutation(test_db, test_admin_user, test_project):
    await _add_inventory_item(test_db, test_project.id)
    model = FakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "list_projects", "args": {}, "id": "call-1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="Here are the projects."),
        ]
    )
    before = (
        await test_db.scalar(select(func.count()).select_from(Project)),
        await test_db.scalar(select(func.count()).select_from(Notification)),
        await test_db.scalar(select(func.count()).select_from(InventoryItem)),
    )
    agent = build_agent(UserRole.ADMIN, model=model)
    ctx = ActorContext.from_user(test_admin_user)
    await run_agent(agent, [("user", "show me my projects")], ctx, test_db)
    after = (
        await test_db.scalar(select(func.count()).select_from(Project)),
        await test_db.scalar(select(func.count()).select_from(Notification)),
        await test_db.scalar(select(func.count()).select_from(InventoryItem)),
    )
    assert before == after


@pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")
async def test_client_agent_menu_excludes_forbidden_tools(test_db, test_client_user, test_project):
    """A client agent is only given the M6-safe tool menu (defense in depth);
    the tools themselves independently deny if reached anyway."""
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    agent = build_agent(UserRole.CLIENT, model=FakeChatModel())  # constructs without error
    menu = {t.name for t in tools_for_role_toolset(UserRole.CLIENT)}
    assert menu == {TOOL_LIST_PROJECTS, TOOL_GET_PROJECT, TOOL_GET_PROJECT_TASKS, TOOL_GET_DAILY_SITE_LOGS, TOOL_GET_INVOICES, TOOL_GET_MY_NOTIFICATIONS, TOOL_WEB_SEARCH} if settings.ICE_AI_WEB_SEARCH_ENABLED else {TOOL_LIST_PROJECTS, TOOL_GET_PROJECT, TOOL_GET_PROJECT_TASKS, TOOL_GET_DAILY_SITE_LOGS, TOOL_GET_INVOICES, TOOL_GET_MY_NOTIFICATIONS}
    assert TOOL_GET_PROJECT_BUDGET not in menu
    assert agent is not None


# --- Runtime-context regression (AI-1.3 hardening) -----------------------------


@pytest.mark.asyncio
async def test_runtime_context_propagates_without_serializer_warning(test_db, test_admin_user):
    """The authenticated ActorContext must reach ToolRuntime.context through the
    PUBLIC LangChain v1 context API (context_schema + context=) with NO Pydantic
    serializer warning, and identity must stay hidden from tool schemas."""
    from langchain_core.messages import HumanMessage
    from langchain_core.messages import ToolMessage

    @lc_tool
    async def probe_actor(runtime: ToolRuntime[ActorContext]) -> dict:
        """Echo the injected actor (test-only)."""
        return {
            "user_id": str(runtime.context.user_id),
            "role": runtime.context.role.value,
        }

    # model-visible schema still hides runtime + identity
    assert "runtime" not in probe_actor.args
    assert "user_id" not in probe_actor.args and "role" not in probe_actor.args

    model = FakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "probe_actor", "args": {}, "id": "call-1", "type": "tool_call"}
                ],
            ),
            AIMessage(content="probe complete"),
        ]
    )
    agent = create_agent(
        model=model,
        tools=[probe_actor],
        system_prompt="You are a read-only ICE assistant.",
        context_schema=ActorContext,
    )
    actor = ActorContext.from_user(test_admin_user)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await run_agent(agent, [HumanMessage(content="probe")], actor, test_db)

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs, "the tool should have executed"
    # ToolRuntime.context carried the injected actor (not a default/None value)
    assert f"{actor.user_id}" in str(tool_msgs[0].content)
    assert actor.role.value in str(tool_msgs[0].content)
    # No Pydantic "Expected none but got ActorContext" serializer warning
    leak = [
        str(w.message)
        for w in caught
        if "Expected" in str(w.message) and "ActorContext" in str(w.message)
    ]
    assert not leak, f"runtime-context serializer warning emitted: {leak[:1]}"


@pytest.mark.asyncio
async def test_stream_assistant_no_serializer_warning(test_db, test_admin_user, test_project):
    """A representative streamed agent run (real ICE tool, typed runtime param)
    must not emit the ActorContext serializer warning through the SSE adapter."""
    model = FakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_project_health",
                        "args": {"project_id": str(test_project.id)},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="The project is on track."),
        ]
    )
    actor = ActorContext.from_user(test_admin_user)
    from app.ai.agent import stream_assistant

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        events = [item async for item in stream_assistant(test_db, actor, "health?", model=model)]
    assert events[0][0] == "assistant_start"
    assert events[-1][0] == "assistant_complete"
    finished = [d for e, d in events if e == "tool_finished"]
    assert finished == [{"tool": "Project health", "ok": True}]
    leak = [
        str(w.message)
        for w in caught
        if "Expected" in str(w.message) and "ActorContext" in str(w.message)
    ]
    assert not leak, f"runtime-context serializer warning emitted: {leak[:1]}"
