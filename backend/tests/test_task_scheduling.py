"""
M12 — Task dependency scheduling & automatic timeline cascade tests.

Splits into two layers:

  * Pure unit tests for `apply_schedule` (no DB): push-only Finish-to-Start,
    transitive propagation, fan-out, idempotency, deterministic fixpoint, and
    the defensive cycle guard.
  * API integration tests: task create/PATCH/delete cascade behavior, audit
    (`task_schedule_shift`) rows, M7 regressions (date order, self, cycle,
    cross-project), RBAC (client 403), and a real separate-session concurrency
    test proving the project row lock yields a deterministic final schedule
    with no lost updates.
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.task import Task, TaskStatus
from app.services.tasks import apply_schedule
from tests.conftest import TEST_DATABASE_URL, auth_header


def _task(
    task_id: uuid.UUID,
    start: date,
    end: date,
    depends_on_id: uuid.UUID | None = None,
    sort_order: int = 0,
) -> Task:
    now = datetime.now(timezone.utc)
    return Task(
        id=task_id,
        project_id=uuid.uuid4(),
        name="t",
        start_date=start,
        end_date=end,
        status=TaskStatus.NOT_STARTED,
        percent_complete=0,
        depends_on_id=depends_on_id,
        sort_order=sort_order,
        created_at=now,
        updated_at=now,
    )


# --- pure apply_schedule unit tests -------------------------------------------


def test_a_to_b_forward_shift():
    a = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 5))
    b = _task(uuid.uuid4(), date(2026, 1, 6), date(2026, 1, 8), depends_on_id=a.id)
    shifts = apply_schedule([a, b])
    assert shifts == []  # B already starts the day after A ends


def test_moving_a_forward_shifts_b():
    a = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 10))
    b = _task(uuid.uuid4(), date(2026, 1, 6), date(2026, 1, 8), depends_on_id=a.id)
    # B starts before A.end + 1 (Jan 11) -> must shift forward by 5 days.
    shifts = apply_schedule([a, b])
    assert len(shifts) == 1
    assert shifts[0].task_id == b.id
    assert shifts[0].old_start == date(2026, 1, 6)
    assert shifts[0].new_start == date(2026, 1, 11)
    assert shifts[0].new_end == date(2026, 1, 13)  # duration preserved (3 days)
    assert shifts[0].caused_by_task_id == a.id
    assert b.start_date == date(2026, 1, 11)
    assert b.end_date == date(2026, 1, 13)


def test_moving_a_backward_does_not_pull_b():
    a = _task(uuid.uuid4(), date(2026, 1, 5), date(2026, 1, 6))
    b = _task(uuid.uuid4(), date(2026, 1, 10), date(2026, 1, 12), depends_on_id=a.id)
    # A moved earlier but B already satisfies F-S (Jan 7 constraint) -> no shift.
    shifts = apply_schedule([a, b])
    assert shifts == []
    assert b.start_date == date(2026, 1, 10)


def test_transitive_chain_three_nodes():
    a = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 5))
    b = _task(uuid.uuid4(), date(2026, 1, 6), date(2026, 1, 7), depends_on_id=a.id)
    c = _task(uuid.uuid4(), date(2026, 1, 8), date(2026, 1, 9), depends_on_id=b.id)
    # Push A's end to Jan 10 -> B starts Jan 11; C then starts Jan 13.
    a.end_date = date(2026, 1, 10)
    shifts = apply_schedule([a, b, c])
    by_id = {s.task_id: s for s in shifts}
    assert set(by_id) == {b.id, c.id}
    assert by_id[b.id].new_start == date(2026, 1, 11)
    assert by_id[b.id].new_end == date(2026, 1, 12)
    assert by_id[c.id].new_start == date(2026, 1, 13)
    assert c.end_date == date(2026, 1, 14)


def test_long_chain_ten_nodes():
    tasks = []
    prev = None
    base = date(2026, 1, 1)
    for i in range(10):
        t = _task(
            uuid.uuid4(),
            base + timedelta(days=3 * i),
            base + timedelta(days=3 * i + 2),
            depends_on_id=prev.id if prev else None,
        )
        tasks.append(t)
        prev = t
    original = {t.id: (t.start_date, t.end_date) for t in tasks}
    # Delay the root by 30 days.
    tasks[0].end_date += timedelta(days=30)
    shifts = apply_schedule(tasks)
    assert len(shifts) == 9
    # Every downstream task shifts forward by exactly 30 days (duration kept).
    for t in tasks[1:]:
        assert t.start_date == original[t.id][0] + timedelta(days=30)
        assert t.end_date == original[t.id][1] + timedelta(days=30)
    # Root start unchanged; only its end moved forward by 30.
    assert tasks[0].start_date == original[tasks[0].id][0]
    assert tasks[0].end_date == original[tasks[0].id][1] + timedelta(days=30)


def test_fan_out_both_successors_shift():
    a = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 10))
    b = _task(uuid.uuid4(), date(2026, 1, 5), date(2026, 1, 6), depends_on_id=a.id)
    c = _task(uuid.uuid4(), date(2026, 1, 5), date(2026, 1, 6), depends_on_id=a.id)
    shifts = apply_schedule([a, b, c])
    assert len(shifts) == 2
    assert b.start_date == date(2026, 1, 11)
    assert c.start_date == date(2026, 1, 11)


def test_no_dependency_no_shift():
    a = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 5))
    b = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 5))
    assert apply_schedule([a, b]) == []


def test_no_unnecessary_shift_and_idempotent():
    a = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 5))
    b = _task(uuid.uuid4(), date(2026, 1, 10), date(2026, 1, 12), depends_on_id=a.id)
    assert apply_schedule([a, b]) == []
    # Idempotent: re-running over an already-consistent schedule changes nothing.
    assert apply_schedule([a, b]) == []


def test_dangling_predecessor_keeps_dates():
    # Predecessor missing from the loaded set (edge pending DB SET NULL) -> no shift.
    missing = uuid.uuid4()
    b = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 5), depends_on_id=missing)
    assert apply_schedule([b]) == []
    assert b.start_date == date(2026, 1, 1)


def test_cycle_guard_raises():
    a = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 5), depends_on_id=None)
    b = _task(uuid.uuid4(), date(2026, 1, 6), date(2026, 1, 10), depends_on_id=a.id)
    a.depends_on_id = b.id  # 2-cycle (defensive; M7 prevents via the API)
    with pytest.raises(RuntimeError, match="cycle"):
        apply_schedule([a, b])


def test_duration_preserved_under_shift():
    a = _task(uuid.uuid4(), date(2026, 1, 1), date(2026, 1, 20))
    b = _task(uuid.uuid4(), date(2026, 1, 10), date(2026, 1, 25), depends_on_id=a.id)
    apply_schedule([a, b])
    assert b.end_date - b.start_date == date(2026, 1, 25) - date(2026, 1, 10)


# --- API integration tests ----------------------------------------------------


async def _create_task(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, **payload
) -> dict:
    body = {
        "name": "Task",
        "start_date": "2026-01-01",
        "end_date": "2026-01-05",
        **payload,
    }
    resp = await client.post(
        f"/api/v1/projects/{project_id}/tasks",
        headers={"Authorization": header},
        json=body,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _audit_actions(db: AsyncSession) -> list[tuple[str, str]]:
    result = await db.execute(select(AuditLog).order_by(AuditLog.created_at))
    return [(r.action, r.record_id) for r in result.scalars().all()]


@pytest.mark.asyncio
async def test_create_with_dependency_auto_shifts_new_task(
    client: httpx.AsyncClient, test_admin_user, test_project, test_db
):
    header = await auth_header(client, "admin@test.com")
    a = await _create_task(client, header, test_project.id, name="A", start_date="2026-01-01", end_date="2026-01-10")
    # B depends on A but starts before A.end + 1 -> B is pushed to Jan 11.
    b = await _create_task(
        client, header, test_project.id, name="B", start_date="2026-01-06", end_date="2026-01-08", depends_on_id=a["id"]
    )
    assert b["start_date"] == "2026-01-11"
    assert b["end_date"] == "2026-01-13"
    actions = await _audit_actions(test_db)
    assert any(action == "task_schedule_shift" for action, _ in actions)


@pytest.mark.asyncio
async def test_patch_moves_predecessor_forward_shifts_dependent(
    client: httpx.AsyncClient, test_admin_user, test_project, test_db
):
    header = await auth_header(client, "admin@test.com")
    a = await _create_task(client, header, test_project.id, name="A", start_date="2026-01-01", end_date="2026-01-05")
    b = await _create_task(client, header, test_project.id, name="B", start_date="2026-01-06", end_date="2026-01-08", depends_on_id=a["id"])
    assert b["start_date"] == "2026-01-06"

    resp = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": header},
        json={"end_date": "2026-01-15"},
    )
    assert resp.status_code == 200

    tasks = (await client.get(f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header})).json()
    by_id = {t["id"]: t for t in tasks}
    assert by_id[b["id"]]["start_date"] == "2026-01-16"
    assert by_id[b["id"]]["end_date"] == "2026-01-18"


@pytest.mark.asyncio
async def test_patch_moves_predecessor_backward_no_pull(
    client: httpx.AsyncClient, test_admin_user, test_project
):
    header = await auth_header(client, "admin@test.com")
    a = await _create_task(client, header, test_project.id, name="A", start_date="2026-02-01", end_date="2026-02-10")
    b = await _create_task(client, header, test_project.id, name="B", start_date="2026-02-20", end_date="2026-02-22", depends_on_id=a["id"])

    await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": header},
        json={"end_date": "2026-02-05"},
    )
    tasks = (await client.get(f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header})).json()
    by_id = {t["id"]: t for t in tasks}
    assert by_id[b["id"]]["start_date"] == "2026-02-20"  # not pulled backward


@pytest.mark.asyncio
async def test_transitive_cascade_via_api(
    client: httpx.AsyncClient, test_admin_user, test_project
):
    header = await auth_header(client, "admin@test.com")
    a = await _create_task(client, header, test_project.id, name="A", start_date="2026-03-01", end_date="2026-03-05")
    b = await _create_task(client, header, test_project.id, name="B", start_date="2026-03-06", end_date="2026-03-07", depends_on_id=a["id"])
    c = await _create_task(client, header, test_project.id, name="C", start_date="2026-03-08", end_date="2026-03-09", depends_on_id=b["id"])

    await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": header},
        json={"end_date": "2026-03-10"},
    )
    tasks = (await client.get(f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header})).json()
    by_id = {t["id"]: t for t in tasks}
    assert by_id[b["id"]]["start_date"] == "2026-03-11"
    assert by_id[c["id"]]["start_date"] == "2026-03-13"


@pytest.mark.asyncio
async def test_audit_rows_for_shifted_dependents_and_no_shift_no_audit(
    client: httpx.AsyncClient, test_admin_user, test_project, test_db
):
    header = await auth_header(client, "admin@test.com")
    a = await _create_task(client, header, test_project.id, name="A", start_date="2026-04-01", end_date="2026-04-05")
    b = await _create_task(client, header, test_project.id, name="B", start_date="2026-04-06", end_date="2026-04-08", depends_on_id=a["id"])
    # No shift should have occurred for B on the second create (already valid).
    actions = await _audit_actions(test_db)
    shift_rows = [(a_, rid) for a_, rid in actions if a_ == "task_schedule_shift"]
    assert shift_rows == []  # B created already F-S valid; no shift audited

    await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": header},
        json={"end_date": "2026-04-12"},
    )
    actions = await _audit_actions(test_db)
    shift_rows = [(a_, rid) for a_, rid in actions if a_ == "task_schedule_shift"]
    assert any(rid == str(b["id"]) for _, rid in shift_rows)

    row = (
        await test_db.execute(
            select(AuditLog).where(
                AuditLog.action == "task_schedule_shift", AuditLog.record_id == str(b["id"])
            )
        )
    ).scalar_one()
    assert row.changes["start_date"]["old"] == "2026-04-06"
    assert row.changes["start_date"]["new"] == "2026-04-13"
    assert row.changes["caused_by_task_id"] == str(a["id"])


@pytest.mark.asyncio
async def test_dependency_change_and_removal(
    client: httpx.AsyncClient, test_admin_user, test_project
):
    header = await auth_header(client, "admin@test.com")
    a = await _create_task(client, header, test_project.id, name="A", start_date="2026-05-01", end_date="2026-05-05")
    b = await _create_task(client, header, test_project.id, name="B", start_date="2026-05-01", end_date="2026-05-03")

    # Point B at a later predecessor A -> B shifts to May 6.
    resp = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{b['id']}",
        headers={"Authorization": header},
        json={"depends_on_id": a["id"]},
    )
    assert resp.status_code == 200
    assert resp.json()["start_date"] == "2026-05-06"

    # Remove the dependency -> dates are kept (D5).
    resp = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{b['id']}",
        headers={"Authorization": header},
        json={"depends_on_id": None},
    )
    assert resp.status_code == 200
    assert resp.json()["start_date"] == "2026-05-06"


@pytest.mark.asyncio
async def test_m7_regressions_still_rejected(
    client: httpx.AsyncClient, test_admin_user, test_project
):
    header = await auth_header(client, "admin@test.com")
    a = await _create_task(client, header, test_project.id, name="A", start_date="2026-06-01", end_date="2026-06-05")
    b = await _create_task(client, header, test_project.id, name="B", start_date="2026-06-06", end_date="2026-06-08")

    # Invalid date range (both dates set) -> 422.
    bad = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{b['id']}",
        headers={"Authorization": header},
        json={"start_date": "2026-06-10", "end_date": "2026-06-05"},
    )
    assert bad.status_code == 422

    # Self dependency -> 400.
    self_dep = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{b['id']}",
        headers={"Authorization": header},
        json={"depends_on_id": b["id"]},
    )
    assert self_dep.status_code == 400

    # Cycle B -> A -> B -> 400.
    await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{b['id']}",
        headers={"Authorization": header},
        json={"depends_on_id": a["id"]},
    )
    cycle = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": header},
        json={"depends_on_id": b["id"]},
    )
    assert cycle.status_code == 400

    # Cross-project dependency -> 400.
    other = await _create_task(client, header, test_project.id, name="C")
    other_proj = (await client.post(
        "/api/v1/projects",
        headers={"Authorization": header},
        json={"name": "Other", "site_address": "x", "client_name": "y", "start_date": "2026-01-01", "target_end_date": "2026-12-31", "budget_total": 1},
    )).json()
    other_proj_task = await _create_task(client, header, other_proj["id"], name="D")
    cross = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{other['id']}",
        headers={"Authorization": header},
        json={"depends_on_id": other_proj_task["id"]},
    )
    assert cross.status_code == 400


@pytest.mark.asyncio
async def test_client_cannot_mutate_tasks(
    client: httpx.AsyncClient, test_admin_user, test_client_user, test_db, test_project
):
    from tests.conftest import assign_user_to_project

    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")
    a = await _create_task(client, admin, test_project.id, name="A")

    header = await auth_header(client, "client@test.com")
    patch = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": header},
        json={"end_date": "2026-12-01"},
    )
    assert patch.status_code == 403
    dep = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": header},
        json={"depends_on_id": str(uuid.uuid4())},
    )
    assert dep.status_code == 403


# --- concurrency (two real DB connections) ------------------------------------


@pytest.fixture
async def concurrent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Per-request DB session so two task PATCHes genuinely race on separate
    connections; the project row lock serializes them (the M1/M7 pattern)."""
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.state.limiter.enabled = False
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_task_updates_deterministic_final_schedule(
    concurrent_client: httpx.AsyncClient, test_admin_user, test_project
):
    """Two simultaneous task PATCHes in the same project (one moving A's end
    forward, one moving B's start forward) serialize on the project row lock:
    final state is deterministic, dependency-consistent, and no update is lost."""
    header = await auth_header(concurrent_client, "admin@test.com")
    a = await _create_task(concurrent_client, header, test_project.id, name="A", start_date="2026-07-01", end_date="2026-07-05")
    b = await _create_task(concurrent_client, header, test_project.id, name="B", start_date="2026-07-06", end_date="2026-07-08", depends_on_id=a["id"])
    assert b["start_date"] == "2026-07-06"

    async def move_a() -> httpx.Response:
        return await concurrent_client.patch(
            f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
            headers={"Authorization": header},
            json={"end_date": "2026-07-20"},
        )

    async def move_b() -> httpx.Response:
        return await concurrent_client.patch(
            f"/api/v1/projects/{test_project.id}/tasks/{b['id']}",
            headers={"Authorization": header},
            json={"start_date": "2026-07-25", "end_date": "2026-07-27"},
        )

    responses = await asyncio.gather(move_a(), move_b())
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]

    tasks = (await concurrent_client.get(f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header})).json()
    by_id = {t["id"]: t for t in tasks}
    a_final, b_final = by_id[a["id"]], by_id[b["id"]]
    # No lost update: A's forward move persisted.
    assert a_final["end_date"] == "2026-07-20"
    # B's manual start persisted and still satisfies F-S (>= A.end + 1).
    assert b_final["start_date"] == "2026-07-25"
    assert b_final["start_date"] >= a_final["end_date"]


@pytest.mark.asyncio
async def test_concurrent_upstream_and_dependent_shift_serialized(
    concurrent_client: httpx.AsyncClient, test_admin_user, test_project
):
    """A dependent-shifting PATCH racing an upstream move yields the same final
    schedule regardless of which wins (row lock; forward-only, idempotent)."""
    header = await auth_header(concurrent_client, "admin@test.com")
    a = await _create_task(concurrent_client, header, test_project.id, name="A", start_date="2026-08-01", end_date="2026-08-05")
    b = await _create_task(concurrent_client, header, test_project.id, name="B", start_date="2026-08-06", end_date="2026-08-08", depends_on_id=a["id"])

    async def move_a() -> httpx.Response:
        return await concurrent_client.patch(
            f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
            headers={"Authorization": header},
            json={"end_date": "2026-08-15"},
        )

    async def push_b() -> httpx.Response:
        return await concurrent_client.patch(
            f"/api/v1/projects/{test_project.id}/tasks/{b['id']}",
            headers={"Authorization": header},
            json={"start_date": "2026-08-10", "end_date": "2026-08-12"},
        )

    responses = await asyncio.gather(move_a(), push_b())
    assert all(r.status_code == 200 for r in responses)

    tasks = (await concurrent_client.get(f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header})).json()
    by_id = {t["id"]: t for t in tasks}
    # Final schedule is deterministic: B.start == max(user B start, A.end + 1).
    expected_b_start = max(date(2026, 8, 10), date(2026, 8, 15) + timedelta(days=1))
    assert by_id[b["id"]]["start_date"] == expected_b_start.isoformat()
    assert by_id[a["id"]]["end_date"] == "2026-08-15"
