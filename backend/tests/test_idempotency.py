"""
M8 — idempotency-key tests.

Covers the retry/replay semantics over the real ASGI client: a key that was
already committed for the same (actor, operation, request) replays the stored
response without re-executing the mutation; a key reused for a *different*
request is a 409; and a failed first attempt leaves the key free for a safe
retry. Concurrency (two in-flight same-key requests) is exercised with
per-request sessions — the DB unique index guarantees exactly one executes and
the loser replays.

Protected endpoints under test: POST job-costs, POST inventory movements, POST
site-logs and POST /projects (create).
"""
import asyncio
import uuid
from datetime import date
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from app.models.idempotency import IdempotencyRecord
from app.models.project import Project
from app.models.user import User
from tests.conftest import TEST_DATABASE_URL, auth_header


def _key() -> str:
    return str(uuid.uuid4())  # 36 chars, within the 8..128 boundary


def cost_payload(**overrides):
    payload = {
        "cost_code": "masonry",
        "description": "Cement blockwork — ground floor",
        "amount": 250000,
        "incurred_on": "2026-08-01",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def concurrent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Client whose requests each get their OWN DB session (like production),
    so two same-key requests genuinely run in separate transactions."""
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
async def test_job_cost_retry_with_same_key_does_not_double_spend(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    key = _key()
    url = f"/api/v1/projects/{test_project.id}/job-costs"

    first = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                              json=cost_payload())
    assert first.status_code == 201

    retry = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                              json=cost_payload())
    assert retry.status_code == 201
    assert retry.json() == first.json()  # verbatim replay of the same resource

    costs = await client.get(url, headers={"Authorization": header})
    assert len(costs.json()) == 1
    project = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert project.json()["budget_spent"] == 250000.0


@pytest.mark.asyncio
async def test_movement_retry_records_one_movement_and_one_ledger_row(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    item = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Cement", "unit": "bags", "opening_quantity": 100},
        )
    ).json()
    url = f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements"
    body = {"movement_type": "consumed", "quantity": 10, "note": "Slab pour"}
    key = _key()

    first = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                              json=body)
    retry = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                              json=body)
    assert first.status_code == 201 and retry.status_code == 201
    assert retry.json() == first.json()

    # Opening-balance movement (100 received) + exactly ONE consumed movement.
    ledger = await client.get(url, headers={"Authorization": header})
    assert len(ledger.json()) == 2

    items = await client.get(
        f"/api/v1/projects/{test_project.id}/inventory", headers={"Authorization": header}
    )
    assert items.json()[0]["quantity_on_hand"] == 90.0


@pytest.mark.asyncio
async def test_site_log_retry_creates_one_entry(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}/site-logs"
    body = {"log_date": "2026-08-01", "work_summary": "Foundation pour"}
    key = _key()

    first = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                              json=body)
    retry = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                              json=body)
    assert first.status_code == 201 and retry.status_code == 201
    assert retry.json() == first.json()

    logs = await client.get(url, headers={"Authorization": header})
    assert len(logs.json()) == 1


@pytest.mark.asyncio
async def test_create_project_retry_creates_one_project(
    client: httpx.AsyncClient, test_admin_user: User
):
    header = await auth_header(client, "admin@test.com")
    body = {
        "name": "Maple Residence",
        "site_address": "42 Maple Rd",
        "client_name": "Maple Co.",
        "start_date": "2026-09-01",
        "target_end_date": "2027-03-01",
        "budget_total": 5000000,
    }
    key = _key()

    first = await client.post(
        "/api/v1/projects", headers={"Authorization": header, "Idempotency-Key": key}, json=body
    )
    retry = await client.post(
        "/api/v1/projects", headers={"Authorization": header, "Idempotency-Key": key}, json=body
    )
    assert first.status_code == 201 and retry.status_code == 201
    assert retry.json() == first.json()

    projects = await client.get("/api/v1/projects", headers={"Authorization": header})
    assert len(projects.json()) == 1
    assert projects.json()[0]["id"] == first.json()["id"]


@pytest.mark.asyncio
async def test_same_key_different_body_conflicts(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}/job-costs"
    key = _key()

    first = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                              json=cost_payload())
    assert first.status_code == 201

    conflict = await client.post(
        url,
        headers={"Authorization": header, "Idempotency-Key": key},
        json=cost_payload(amount=999999),
    )
    assert conflict.status_code == 409
    assert "different request" in conflict.json()["detail"]


@pytest.mark.asyncio
async def test_same_key_different_project_conflicts(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    key = _key()
    url_a = f"/api/v1/projects/{test_project.id}/job-costs"
    assert (
        await client.post(url_a, headers={"Authorization": header, "Idempotency-Key": key},
                          json=cost_payload())
    ).status_code == 201

    other = Project(
        project_code="PRJ-TEST-0002",
        name="Other Site",
        site_address="1 Other St",
        client_name="Other Co.",
        status="active",
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        budget_total=100000,
    )
    test_db.add(other)
    await test_db.commit()
    await test_db.refresh(other)

    url_b = f"/api/v1/projects/{other.id}/job-costs"
    conflict = await client.post(
        url_b, headers={"Authorization": header, "Idempotency-Key": key}, json=cost_payload()
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_key_namespaced_per_operation(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    """The same key may be reused across DIFFERENT operations (route templates)."""
    header = await auth_header(client, "admin@test.com")
    key = _key()

    cost = await client.post(
        f"/api/v1/projects/{test_project.id}/job-costs",
        headers={"Authorization": header, "Idempotency-Key": key},
        json=cost_payload(),
    )
    assert cost.status_code == 201

    item = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Steel", "unit": "kg", "opening_quantity": 50},
        )
    ).json()
    movement = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements",
        headers={"Authorization": header, "Idempotency-Key": key},
        json={"movement_type": "consumed", "quantity": 5},
    )
    assert movement.status_code == 201


@pytest.mark.asyncio
async def test_key_namespaced_per_user(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_procurement_user: User,
    test_project: Project,
):
    """Two actors reusing the same key are independent namespaces — both succeed."""
    key = _key()
    url = f"/api/v1/projects/{test_project.id}/job-costs"

    admin_header = await auth_header(client, "admin@test.com")
    first = await client.post(url, headers={"Authorization": admin_header, "Idempotency-Key": key},
                              json=cost_payload())
    assert first.status_code == 201

    proc_header = await auth_header(client, "procurement@test.com")
    second = await client.post(url, headers={"Authorization": proc_header, "Idempotency-Key": key},
                               json=cost_payload())
    assert second.status_code == 201
    assert second.json()["id"] != first.json()["id"]


@pytest.mark.asyncio
async def test_failed_first_attempt_frees_key_for_retry(
    concurrent_client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_admin_user: User,
    test_project: Project,
):
    """A failed attempt rolls the claim back, so the key stays free for a safe
    retry. Uses per-request sessions (like production) because the failed
    request must tear its transaction down before the retry runs."""
    header = await auth_header(concurrent_client, "admin@test.com")
    item = (
        await concurrent_client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Bricks", "unit": "pcs", "opening_quantity": 10},
        )
    ).json()
    url = f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements"
    key = _key()

    # First attempt fails validation (below-zero) — the claim rolls back with it.
    failed = await concurrent_client.post(
        url,
        headers={"Authorization": header, "Idempotency-Key": key},
        json={"movement_type": "consumed", "quantity": 500},
    )
    assert failed.status_code == 400

    # The SAME key is free again for a valid retry.
    ok = await concurrent_client.post(
        url,
        headers={"Authorization": header, "Idempotency-Key": key},
        json={"movement_type": "received", "quantity": 5},
    )
    assert ok.status_code == 201

    ledger = await concurrent_client.get(url, headers={"Authorization": header})
    # Opening balance (10) + the one successful received movement.
    assert len(ledger.json()) == 2
    items = await concurrent_client.get(
        f"/api/v1/projects/{test_project.id}/inventory", headers={"Authorization": header}
    )
    assert items.json()[0]["quantity_on_hand"] == 15.0


@pytest.mark.asyncio
async def test_replay_for_archived_project_returns_cached_response(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    """A replayed mutation never re-runs business logic — the archived guard is
    bypassed by the cached response, and no new record is created."""
    header = await auth_header(client, "admin@test.com")
    key = _key()
    url = f"/api/v1/projects/{test_project.id}/job-costs"

    first = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                              json=cost_payload())
    assert first.status_code == 201

    archived = await client.post(
        f"/api/v1/projects/{test_project.id}/archive", headers={"Authorization": header}
    )
    assert archived.status_code == 200

    retry = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                              json=cost_payload())
    assert retry.status_code == 201  # cached replay, not 409/archived
    assert retry.json() == first.json()

    costs = await client.get(url, headers={"Authorization": header})
    assert len(costs.json()) == 1


@pytest.mark.asyncio
async def test_invalid_key_length_rejected(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}/job-costs"

    short = await client.post(
        url, headers={"Authorization": header, "Idempotency-Key": "short"}, json=cost_payload()
    )
    assert short.status_code == 400

    long = await client.post(
        url,
        headers={"Authorization": header, "Idempotency-Key": "k" * 200},
        json=cost_payload(),
    )
    assert long.status_code == 400


@pytest.mark.asyncio
async def test_mutation_without_key_still_works(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/job-costs",
        headers={"Authorization": header},
        json=cost_payload(),
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_claim_completed_and_replayed_not_duplicated(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    """The idempotency_records table holds one completed claim per key; a retry
    does not add a second row."""
    header = await auth_header(client, "admin@test.com")
    key = _key()
    url = f"/api/v1/projects/{test_project.id}/job-costs"

    await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                      json=cost_payload())
    await client.post(url, headers={"Authorization": header, "Idempotency-Key": key},
                      json=cost_payload())

    rows = (
        await test_db.execute(select(IdempotencyRecord))
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].idempotency_key == key
    assert rows[0].response_status == 201
    assert rows[0].response_body is not None


@pytest.mark.asyncio
async def test_concurrent_same_key_executes_once(
    concurrent_client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_admin_user: User,
    test_project: Project,
):
    """Two in-flight requests with the same key: exactly one business operation
    executes; the loser replays the winner's response."""
    header = await auth_header(concurrent_client, "admin@test.com")
    item = (
        await concurrent_client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Concrete", "unit": "m3", "opening_quantity": 100},
        )
    ).json()
    url = f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements"
    key = _key()
    body = {"movement_type": "consumed", "quantity": 30}

    async def send() -> httpx.Response:
        return await concurrent_client.post(
            url, headers={"Authorization": header, "Idempotency-Key": key}, json=body
        )

    responses = await asyncio.gather(send(), send())
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"]

    ledger = (
        await concurrent_client.get(url, headers={"Authorization": header})
    ).json()
    # Opening-balance movement (100) + exactly ONE consumed movement.
    assert len(ledger) == 2
    items = (
        await concurrent_client.get(
            f"/api/v1/projects/{test_project.id}/inventory", headers={"Authorization": header}
        )
    ).json()
    assert items[0]["quantity_on_hand"] == 70.0

    rows = (
        await test_db.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key)
        )
    ).scalars().all()
    assert len(rows) == 1
