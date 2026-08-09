"""
Tests for inventory item and stock movement endpoints and their RBAC rules.
"""
import httpx
import pytest

from app.models.project import Project
from app.models.user import User
from tests.conftest import auth_header


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
