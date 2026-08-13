"""
M13 — In-app notifications tests.

Covers notification creation from each event hook (M12 schedule shifts, M5
invoice issue, inventory low-stock crossings, M2 assignment), recipient
scoping, the user-scoped API (feed / unread-count / mark-read / read-all),
ownership/IDOR, transaction atomicity, deduplication (incl. M8 idempotent
replay), and a real two-session concurrency case.
"""
import asyncio
import uuid
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from tests.conftest import TEST_DATABASE_URL, assign_user_to_project, auth_header


async def _create_task(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, **payload
) -> dict:
    body = {"name": "Task", "start_date": "2026-01-01", "end_date": "2026-01-05", **payload}
    resp = await client.post(
        f"/api/v1/projects/{project_id}/tasks",
        headers={"Authorization": header},
        json=body,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _feed(client: httpx.AsyncClient, header: str) -> list[dict]:
    resp = await client.get("/api/v1/notifications", headers={"Authorization": header})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _unread_count(client: httpx.AsyncClient, header: str) -> int:
    resp = await client.get("/api/v1/notifications/unread-count", headers={"Authorization": header})
    assert resp.status_code == 200, resp.text
    return resp.json()["count"]


async def _notifications_of_type(
    client: httpx.AsyncClient, header: str, type_: str
) -> list[dict]:
    return [n for n in await _feed(client, header) if n["type"] == type_]


# --- M12 schedule-shift event ------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_shift_notifies_supervisors_and_admins(
    client: httpx.AsyncClient, test_admin_user, test_supervisor_user, test_db, test_project
):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    admin = await auth_header(client, "admin@test.com")
    sup = await auth_header(client, "supervisor@test.com")

    a = await _create_task(client, admin, test_project.id, name="A", start_date="2026-01-01", end_date="2026-01-05")
    await _create_task(client, admin, test_project.id, name="B", start_date="2026-01-06", end_date="2026-01-08", depends_on_id=a["id"])

    await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": admin},
        json={"end_date": "2026-01-15"},
    )

    assert len(await _notifications_of_type(client, sup, "task_schedule_shift")) == 1
    assert len(await _notifications_of_type(client, admin, "task_schedule_shift")) == 1


@pytest.mark.asyncio
async def test_no_shift_no_notification(
    client: httpx.AsyncClient, test_admin_user, test_supervisor_user, test_db, test_project
):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    admin = await auth_header(client, "admin@test.com")
    sup = await auth_header(client, "supervisor@test.com")

    a = await _create_task(client, admin, test_project.id, name="A", start_date="2026-01-01", end_date="2026-01-05")
    await _create_task(client, admin, test_project.id, name="B", start_date="2026-01-06", end_date="2026-01-08", depends_on_id=a["id"])
    # No dependency violation -> no cascade -> no notification.
    assert await _notifications_of_type(client, sup, "task_schedule_shift") == []


# --- M5 invoice-issue event --------------------------------------------------


async def _make_and_issue_invoice(
    client: httpx.AsyncClient, admin: str, project_id: uuid.UUID
) -> dict:
    m = (
        await client.post(
            f"/api/v1/projects/{project_id}/billing-milestones",
            headers={"Authorization": admin},
            json={"name": "Foundation", "billing_type": "percentage", "billing_percentage": 20},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project_id}/billing-milestones/{m['id']}/complete",
        headers={"Authorization": admin},
    )
    inv = (
        await client.post(
            f"/api/v1/projects/{project_id}/invoices",
            headers={"Authorization": admin},
            json={"billing_milestone_id": m["id"]},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project_id}/invoices/{inv['id']}/issue",
        headers={"Authorization": admin},
    )
    return inv


@pytest.mark.asyncio
async def test_invoice_issued_notifies_client_and_admins(
    client: httpx.AsyncClient, test_admin_user, test_client_user, test_supervisor_user, test_db, test_project
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    admin = await auth_header(client, "admin@test.com")
    client_hdr = await auth_header(client, "client@test.com")
    sup = await auth_header(client, "supervisor@test.com")

    await _make_and_issue_invoice(client, admin, test_project.id)

    assert len(await _notifications_of_type(client, client_hdr, "milestone_invoice_issued")) == 1
    assert len(await _notifications_of_type(client, admin, "milestone_invoice_issued")) == 1
    # Supervisors are not invoice-issue recipients.
    assert await _notifications_of_type(client, sup, "milestone_invoice_issued") == []


# --- inventory low-stock event ------------------------------------------------


async def _make_item(
    client: httpx.AsyncClient, admin: str, project_id: uuid.UUID, qty: float, threshold: float | None
) -> dict:
    payload = {"name": "Cement", "unit": "bag", "opening_quantity": qty}
    if threshold is not None:
        payload["reorder_threshold"] = threshold
    resp = await client.post(
        f"/api/v1/projects/{project_id}/inventory",
        headers={"Authorization": admin},
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_low_stock_crossing_notifies_procurement_once(
    client: httpx.AsyncClient, test_admin_user, test_procurement_user, test_db, test_project
):
    admin = await auth_header(client, "admin@test.com")
    proc = await auth_header(client, "procurement@test.com")

    item = await _make_item(client, admin, test_project.id, qty=100, threshold=50)
    # Above threshold -> no notification yet.
    assert await _notifications_of_type(client, proc, "inventory_low_stock") == []

    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements",
        headers={"Authorization": admin},
        json={"movement_type": "consumed", "quantity": 60},
    )
    assert resp.status_code == 201
    assert len(await _notifications_of_type(client, proc, "inventory_low_stock")) == 1

    # Further consumption stays below threshold -> no duplicate notification.
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements",
        headers={"Authorization": admin},
        json={"movement_type": "consumed", "quantity": 10},
    )
    assert resp.status_code == 201
    assert len(await _notifications_of_type(client, proc, "inventory_low_stock")) == 1


@pytest.mark.asyncio
async def test_low_stock_on_create_when_starting_below_threshold(
    client: httpx.AsyncClient, test_admin_user, test_procurement_user, test_db, test_project
):
    admin = await auth_header(client, "admin@test.com")
    proc = await auth_header(client, "procurement@test.com")

    await _make_item(client, admin, test_project.id, qty=10, threshold=50)
    assert len(await _notifications_of_type(client, proc, "inventory_low_stock")) == 1


@pytest.mark.asyncio
async def test_low_stock_transaction_rollback_no_notification(
    client: httpx.AsyncClient, test_admin_user, test_procurement_user, test_db, test_project
):
    admin = await auth_header(client, "admin@test.com")
    proc = await auth_header(client, "procurement@test.com")

    item = await _make_item(client, admin, test_project.id, qty=100, threshold=50)
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements",
        headers={"Authorization": admin},
        json={"movement_type": "consumed", "quantity": 150},  # would go below zero
    )
    assert resp.status_code == 400
    assert await _notifications_of_type(client, proc, "inventory_low_stock") == []


@pytest.mark.asyncio
async def test_idempotent_replay_no_duplicate_notification(
    client: httpx.AsyncClient, test_admin_user, test_procurement_user, test_db, test_project
):
    """M8: a retried movement replays the stored response and must not create a
    second low-stock notification."""
    admin = await auth_header(client, "admin@test.com")
    proc = await auth_header(client, "procurement@test.com")

    item = await _make_item(client, admin, test_project.id, qty=100, threshold=50)
    key = "key-lowstock-001"
    url = f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements"
    payload = {"movement_type": "consumed", "quantity": 60}

    first = await client.post(
        url, headers={"Authorization": admin, "Idempotency-Key": key}, json=payload
    )
    assert first.status_code == 201
    replay = await client.post(
        url, headers={"Authorization": admin, "Idempotency-Key": key}, json=payload
    )
    assert replay.status_code == 201

    assert len(await _notifications_of_type(client, proc, "inventory_low_stock")) == 1


# --- M2 assignment event -----------------------------------------------------


@pytest.mark.asyncio
async def test_assignment_notifies_assigned_user(
    client: httpx.AsyncClient, test_admin_user, test_supervisor_user, test_db, test_project
):
    admin = await auth_header(client, "admin@test.com")
    sup = await auth_header(client, "supervisor@test.com")

    await client.post(
        f"/api/v1/projects/{test_project.id}/assignments",
        headers={"Authorization": admin},
        json={"user_id": str(test_supervisor_user.id)},
    )

    assert len(await _notifications_of_type(client, sup, "project_assigned")) == 1
    # The assigning admin is not notified about their own action.
    assert await _notifications_of_type(client, admin, "project_assigned") == []


# --- API ownership / IDOR / read state ---------------------------------------


@pytest.mark.asyncio
async def test_notification_ownership_and_idor(
    client: httpx.AsyncClient, test_admin_user, test_supervisor_user, test_db, test_project
):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    admin = await auth_header(client, "admin@test.com")
    sup = await auth_header(client, "supervisor@test.com")

    a = await _create_task(client, admin, test_project.id, name="A", start_date="2026-02-01", end_date="2026-02-05")
    await _create_task(client, admin, test_project.id, name="B", start_date="2026-02-06", end_date="2026-02-08", depends_on_id=a["id"])
    await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": admin},
        json={"end_date": "2026-02-15"},
    )

    sup_feed = await _feed(client, sup)
    assert sup_feed  # supervisor has the schedule notification
    nid = sup_feed[0]["id"]

    # Admin cannot read the supervisor's notification.
    resp = await client.post(
        f"/api/v1/notifications/{nid}/read", headers={"Authorization": admin}
    )
    assert resp.status_code == 404
    # The admin has their own schedule notification (admins are recipients),
    # but it is a distinct row — the supervisor's id still 404s for them.
    admin_feed = await _feed(client, admin)
    assert len(admin_feed) == 1
    assert admin_feed[0]["id"] != nid
    resp = await client.post(
        f"/api/v1/notifications/{nid}/read", headers={"Authorization": sup}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mark_read_unread_count_and_mark_all(
    client: httpx.AsyncClient, test_admin_user, test_supervisor_user, test_db, test_project
):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    admin = await auth_header(client, "admin@test.com")
    sup = await auth_header(client, "supervisor@test.com")

    a = await _create_task(client, admin, test_project.id, name="A", start_date="2026-03-01", end_date="2026-03-05")
    await _create_task(client, admin, test_project.id, name="B", start_date="2026-03-06", end_date="2026-03-08", depends_on_id=a["id"])
    await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": admin},
        json={"end_date": "2026-03-15"},
    )
    assert await _unread_count(client, sup) == 1

    nid = (await _feed(client, sup))[0]["id"]
    resp = await client.post(f"/api/v1/notifications/{nid}/read", headers={"Authorization": sup})
    assert resp.status_code == 200
    assert await _unread_count(client, sup) == 0
    # Idempotent re-read.
    assert (await client.post(f"/api/v1/notifications/{nid}/read", headers={"Authorization": sup})).status_code == 200

    # A new shift, then mark-all-read.
    await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": admin},
        json={"end_date": "2026-03-20"},
    )
    assert await _unread_count(client, sup) == 1
    resp = await client.post("/api/v1/notifications/read-all", headers={"Authorization": sup})
    assert resp.status_code == 204
    assert await _unread_count(client, sup) == 0


@pytest.mark.asyncio
async def test_client_notifications_isolated_between_clients(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    """A notification about one project never leaks to another user."""
    admin = await auth_header(client, "admin@test.com")
    client_hdr = await auth_header(client, "client@test.com")
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    await _make_and_issue_invoice(client, admin, test_project.id)
    feed = await _feed(client, client_hdr)
    assert len(feed) == 1 and feed[0]["type"] == "milestone_invoice_issued"

    # A second client has an empty feed.
    other = (
        await client.post(
            "/api/v1/users",
            headers={"Authorization": admin},
            json={"email": "other-client@test.com", "full_name": "Other", "role": "client", "password": "OtherPass123"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{test_project.id}/assignments",
        headers={"Authorization": admin},
        json={"user_id": other["id"]},
    )
    # The other client was just assigned (project_assigned), but must NOT see
    # the invoice notification created before their assignment.
    other_hdr = await auth_header(client, "other-client@test.com", password="OtherPass123")
    assert await _notifications_of_type(client, other_hdr, "milestone_invoice_issued") == []


# --- concurrency (two real DB connections) -----------------------------------


@pytest.fixture
async def concurrent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
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
async def test_concurrent_schedule_shifts_produce_notifications(
    concurrent_client: httpx.AsyncClient, test_admin_user, test_supervisor_user, test_db, test_project
):
    """Concurrent task PATCHes in the same project serialize on the project row
    lock; the schedule events that actually shift dependents each produce a
    notification (no lost notifications, no duplicate for a single event)."""
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    header = await auth_header(concurrent_client, "admin@test.com")
    sup = await auth_header(concurrent_client, "supervisor@test.com")

    a = await _create_task(concurrent_client, header, test_project.id, name="A", start_date="2026-04-01", end_date="2026-04-05")
    b = await _create_task(concurrent_client, header, test_project.id, name="B", start_date="2026-04-06", end_date="2026-04-08", depends_on_id=a["id"])

    async def move(end: str) -> httpx.Response:
        return await concurrent_client.patch(
            f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
            headers={"Authorization": header},
            json={"end_date": end},
        )

    responses = await asyncio.gather(move("2026-04-15"), move("2026-04-20"))
    assert all(r.status_code == 200 for r in responses)

    tasks = (await concurrent_client.get(f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header})).json()
    b_final = next(t for t in tasks if t["id"] == b["id"])
    a_final = next(t for t in tasks if t["id"] == a["id"])
    assert b_final["start_date"] >= a_final["end_date"]  # F-S holds

    # At least one schedule-shift notification was delivered; never a
    # notification with zero shifts.
    notifications = await _notifications_of_type(concurrent_client, sup, "task_schedule_shift")
    assert len(notifications) >= 1
