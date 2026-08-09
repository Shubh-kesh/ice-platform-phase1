"""
Tests for inventory item and stock movement endpoints and their RBAC rules.
"""
import asyncio
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from app.models.inventory import InventoryItem
from app.models.project import Project
from app.models.user import User
from tests.conftest import TEST_DATABASE_URL, auth_header


@pytest.fixture
async def concurrent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    HTTP client whose requests each get their OWN database session (like the
    real app), so concurrent requests run in separate transactions. Needed to
    exercise the row-lock serialization — the plain `client` fixture shares one
    session and therefore can't demonstrate inter-transaction races.
    """
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
async def test_procurement_can_create_item_with_opening_balance(
    client: httpx.AsyncClient, test_procurement_user: User, test_project: Project
):
    header = await auth_header(client, "procurement@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory",
        headers={"Authorization": header},
        json={"name": "Cement (OPC 53)", "unit": "bags", "opening_quantity": 200},
    )
    assert resp.status_code == 201
    item = resp.json()
    assert item["quantity_on_hand"] == 200.0


@pytest.mark.asyncio
async def test_supervisor_cannot_create_inventory_item(
    client: httpx.AsyncClient, test_supervisor_user: User, test_project: Project
):
    header = await auth_header(client, "supervisor@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory",
        headers={"Authorization": header},
        json={"name": "Steel Rebar", "unit": "kg"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_consumption_reduces_balance(
    client: httpx.AsyncClient, test_procurement_user: User, test_project: Project
):
    header = await auth_header(client, "procurement@test.com")
    item = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Sand", "unit": "m3", "opening_quantity": 50},
        )
    ).json()

    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements",
        headers={"Authorization": header},
        json={"movement_type": "consumed", "quantity": 20, "note": "Used for slab"},
    )
    assert resp.status_code == 201

    updated = (
        await client.get(f"/api/v1/projects/{test_project.id}/inventory", headers={"Authorization": header})
    ).json()
    assert updated[0]["quantity_on_hand"] == 30.0


@pytest.mark.asyncio
async def test_movement_cannot_take_balance_below_zero(
    client: httpx.AsyncClient, test_procurement_user: User, test_project: Project
):
    header = await auth_header(client, "procurement@test.com")
    item = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Bricks", "unit": "pcs", "opening_quantity": 10},
        )
    ).json()

    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements",
        headers={"Authorization": header},
        json={"movement_type": "consumed", "quantity": 50},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_movement_ledger_is_listable(
    client: httpx.AsyncClient, test_procurement_user: User, test_project: Project
):
    header = await auth_header(client, "procurement@test.com")
    item = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Paint", "unit": "litres", "opening_quantity": 100},
        )
    ).json()

    await client.post(
        f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements",
        headers={"Authorization": header},
        json={"movement_type": "consumed", "quantity": 10},
    )

    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements",
        headers={"Authorization": header},
    )
    assert resp.status_code == 200
    # Opening balance movement + the consumption movement
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_reconciliation_balance_matches_ledger(
    client: httpx.AsyncClient, test_procurement_user: User, test_project: Project
):
    header = await auth_header(client, "procurement@test.com")
    item = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Cement (OPC 53)", "unit": "bags", "opening_quantity": 100},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements",
        headers={"Authorization": header},
        json={"movement_type": "consumed", "quantity": 20, "note": "Slab pour"},
    )

    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/inventory/reconciliation",
        headers={"Authorization": header},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["item_id"] == item["id"]
    assert rows[0]["quantity_on_hand"] == 80.0
    assert rows[0]["ledger_balance"] == 80.0
    assert rows[0]["matches"] is True


@pytest.mark.asyncio
async def test_reconciliation_flags_ledger_mismatch(
    client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_procurement_user: User,
    test_project: Project,
):
    header = await auth_header(client, "procurement@test.com")
    item = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Steel Rebar", "unit": "kg", "opening_quantity": 100},
        )
    ).json()

    # Simulate a legacy lost-update race: drift the running total away from the
    # ledger without appending a movement (direct DB write, not via the API).
    stored = (await test_db.execute(select(InventoryItem).where(InventoryItem.id == item["id"]))).scalar_one()
    stored.quantity_on_hand = 70.0
    await test_db.commit()

    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/inventory/reconciliation",
        headers={"Authorization": header},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["quantity_on_hand"] == 70.0
    assert rows[0]["ledger_balance"] == 100.0
    assert rows[0]["matches"] is False


@pytest.mark.asyncio
async def test_supervisor_cannot_read_reconciliation(
    client: httpx.AsyncClient, test_supervisor_user: User, test_project: Project
):
    header = await auth_header(client, "supervisor@test.com")
    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/inventory/reconciliation",
        headers={"Authorization": header},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_concurrent_movements_no_lost_update(
    concurrent_client: httpx.AsyncClient,
    test_project: Project,
    test_procurement_user: User,
):
    header = await auth_header(concurrent_client, "procurement@test.com")
    item = (
        await concurrent_client.post(
            f"/api/v1/projects/{test_project.id}/inventory",
            headers={"Authorization": header},
            json={"name": "Concrete", "unit": "m3", "opening_quantity": 100},
        )
    ).json()
    item_id = item["id"]

    async def consume(quantity: float) -> httpx.Response:
        return await concurrent_client.post(
            f"/api/v1/projects/{test_project.id}/inventory/{item_id}/movements",
            headers={"Authorization": header},
            json={"movement_type": "consumed", "quantity": quantity},
        )

    responses = await asyncio.gather(consume(30), consume(30))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]

    updated = (
        await concurrent_client.get(
            f"/api/v1/projects/{test_project.id}/inventory", headers={"Authorization": header}
        )
    ).json()
    assert updated[0]["quantity_on_hand"] == 40.0

    ledger = (
        await concurrent_client.get(
            f"/api/v1/projects/{test_project.id}/inventory/{item_id}/movements",
            headers={"Authorization": header},
        )
    ).json()
    # Opening balance + the two consumed movements — nothing dropped.
    assert len(ledger) == 3
