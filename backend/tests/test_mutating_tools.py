"""
W7.4 — direct mutating-tool behavior (create_task / create_daily_site_log).

Every tool is exercised directly (fabricated ToolRuntime + bound session) to
pin the deterministic contract: RBAC role gates, project visibility/IDOR,
archived read-only, validation, transaction rollback, audit rows and result
shape. These are the SAME rules the REST routes enforce — the tool reuses them.
"""
import uuid
from datetime import date

import pytest
from langchain.tools import ToolRuntime
from sqlalchemy import func, select

from app.ai.context import ActorContext, session_scope
from app.ai.security import MUTATING_TOOLS
from app.ai.tools.mutating import create_daily_site_log, create_task
from app.core.config import settings
from app.models.audit import AuditLog
from app.models.project import ProjectStatus
from app.models.site_log import DailySiteLog
from app.models.task import Task
from app.models.user import UserRole
from tests.conftest import assign_user_to_project

pytestmark = pytest.mark.filterwarnings("ignore:Pydantic serializer warnings")


def make_runtime(user_id, role) -> ToolRuntime:
    return ToolRuntime(
        state={},
        context=ActorContext(user_id=user_id, role=role),
        config={},
        stream_writer=lambda *a, **k: None,
        tool_call_id=None,
        store=None,
    )


async def _count(db, model):
    result = await db.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def _call_create_task(db, user, project_id, **overrides):
    args = {
        "project_id": project_id,
        "name": "Foundation inspection",
        "start_date": date(2026, 8, 16),
        "end_date": date(2026, 8, 16),
        "runtime": make_runtime(user.id, user.role),
    }
    args.update(overrides)
    async with session_scope(db):
        return await create_task.ainvoke(args)


async def _call_create_site_log(db, user, project_id, **overrides):
    args = {
        "project_id": project_id,
        "log_date": date(2026, 8, 16),
        "work_summary": "Rework and survey",
        "runtime": make_runtime(user.id, user.role),
    }
    args.update(overrides)
    async with session_scope(db):
        return await create_daily_site_log.ainvoke(args)


# --- RBAC role gates ---------------------------------------------------------------


async def test_create_task_admin_allowed(test_db, test_admin_user, test_project):
    result = await _call_create_task(test_db, test_admin_user, test_project.id)
    assert result.get("ok") is True
    assert result.get("name") == "Foundation inspection"
    tasks = (await test_db.execute(select(Task))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].project_id == test_project.id
    # audit row in the same transaction
    audits = (await test_db.execute(select(AuditLog))).scalars().all()
    assert any(r.action == "create" and r.table_name == "tasks" for r in audits)


async def test_create_task_supervisor_assigned_allowed(test_db, test_supervisor_user, test_project):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    result = await _call_create_task(test_db, test_supervisor_user, test_project.id)
    assert result.get("ok") is True
    assert await _count(test_db, Task) == 1


async def test_create_task_supervisor_unassigned_denied(test_db, test_supervisor_user, test_project):
    result = await _call_create_task(test_db, test_supervisor_user, test_project.id)
    assert result.get("error") == "not_permitted"
    assert await _count(test_db, Task) == 0


async def test_create_task_procurement_denied(test_db, test_procurement_user, test_project):
    # REST parity: procurement writes POs/inventory, NOT schedule tasks.
    result = await _call_create_task(test_db, test_procurement_user, test_project.id)
    assert result.get("error") == "not_permitted"
    assert await _count(test_db, Task) == 0


async def test_create_task_client_denied(test_db, test_client_user, test_project):
    result = await _call_create_task(test_db, test_client_user, test_project.id)
    assert result.get("error") == "not_permitted"
    assert await _count(test_db, Task) == 0


async def test_site_log_admin_allowed_and_audited(test_db, test_admin_user, test_project):
    result = await _call_create_site_log(test_db, test_admin_user, test_project.id)
    assert result.get("ok") is True
    logs = (await test_db.execute(select(DailySiteLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].created_by == test_admin_user.id
    audits = (await test_db.execute(select(AuditLog))).scalars().all()
    assert any(r.action == "create" and r.table_name == "daily_site_logs" for r in audits)


async def test_site_log_client_denied(test_db, test_client_user, test_project):
    result = await _call_create_site_log(test_db, test_client_user, test_project.id)
    assert result.get("error") == "not_permitted"
    assert await _count(test_db, DailySiteLog) == 0


# --- IDOR / archived / validation / rollback ----------------------------------------


async def test_supervisor_idor_other_project_denied(test_db, test_supervisor_user, test_project):
    from app.models.project import Project

    project2 = Project(
        project_code="PRJ-OTHER-0001",
        name="Other Residence",
        site_address="99 Other St",
        client_name="Other Client",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        budget_total=500000,
    )
    test_db.add(project2)
    await test_db.commit()
    result = await _call_create_task(test_db, test_supervisor_user, project2.id)
    assert result.get("error") == "not_permitted"
    assert await _count(test_db, Task) == 0


async def test_create_task_archived_project_denied(test_db, test_admin_user, test_project):
    test_project.status = ProjectStatus.ARCHIVED
    await test_db.commit()
    result = await _call_create_task(test_db, test_admin_user, test_project.id)
    assert result.get("error") == "not_permitted"
    assert await _count(test_db, Task) == 0


async def test_create_site_log_archived_project_denied(test_db, test_admin_user, test_project):
    test_project.status = ProjectStatus.ARCHIVED
    await test_db.commit()
    result = await _call_create_site_log(test_db, test_admin_user, test_project.id)
    assert result.get("error") == "not_permitted"
    assert await _count(test_db, DailySiteLog) == 0


async def test_create_task_invalid_date_order_rolls_back(test_db, test_admin_user, test_project):
    result = await _call_create_task(
        test_db, test_admin_user, test_project.id,
        start_date=date(2026, 8, 20), end_date=date(2026, 8, 10),
    )
    assert result.get("error") is not None
    assert await _count(test_db, Task) == 0
    assert await _count(test_db, AuditLog) == 0


async def test_create_task_missing_dependency_rolls_back(test_db, test_admin_user, test_project):
    result = await _call_create_task(
        test_db, test_admin_user, test_project.id,
        depends_on_id=uuid.uuid4(),
    )
    assert result.get("error") is not None
    assert await _count(test_db, Task) == 0


async def test_create_site_log_duplicate_date_rejected(test_db, test_admin_user, test_project):
    first = await _call_create_site_log(test_db, test_admin_user, test_project.id)
    assert first.get("ok") is True
    second = await _call_create_site_log(test_db, test_admin_user, test_project.id)
    assert second.get("error") is not None
    assert await _count(test_db, DailySiteLog) == 1


async def test_result_shape_is_safe_dict(test_db, test_admin_user, test_project):
    result = await _call_create_task(test_db, test_admin_user, test_project.id)
    assert set(result.keys()) == {"ok", "task_id", "name", "status", "start_date", "end_date"}
    assert "user_id" not in result and "role" not in result
    assert isinstance(result["task_id"], str)


# --- role toolset never leaks mutating tools to client -----------------------------


async def test_client_and_procurement_toolset_excludes_mutations(
    test_db, test_client_user, test_procurement_user, monkeypatch
):
    monkeypatch.setattr(settings, "ICE_AI_MUTATIONS_ENABLED", True)
    from app.ai.agent import tools_for_role_toolset

    for user in (test_client_user, test_procurement_user):
        names = {t.name for t in tools_for_role_toolset(user.role)}
        assert not (names & MUTATING_TOOLS)
    # admin + supervisor DO get them
    from app.ai.agent import tools_for_role_toolset as _trt
    admin_names = {t.name for t in _trt(UserRole.ADMIN)}
    assert MUTATING_TOOLS <= admin_names
