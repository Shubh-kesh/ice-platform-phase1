"""
M6 — Client portal boundary tests.

The CLIENT role is the portal-facing persona. These tests pin the exact
server-side contract the SPA client portal depends on:

  * Project reads: the tight ProjectClientRead shape on both list and detail
    — no budget figures, no manual health columns, no lifecycle attribution
    (created_by/completed_by/archived_by/restored_by), no internal
    created_at/updated_at bookkeeping.
  * Health: 403 for clients on both the roll-up and per-project endpoints —
    computed health (colors, reasons, basis) is an internal management signal,
    not part of the client portal.
  * Inventory/procurement: 403 for clients — the stock-movement ledger and
    unit costs are internal.
  * Invoices: clients see issued payment requests only. DRAFT invoices are
    hidden from the list and return 404 on detail (their existence is never
    leaked). SENT/PAID/CANCELLED return the restricted InvoiceClientRead
    shape.
  * Writes: clients are read-only in this phase — the role-gated write
    endpoints already reject with 403 (asserted for tasks, milestones and
    inventory for the record).
"""
import uuid

import httpx
import pytest

from tests.conftest import assign_user_to_project, auth_header


CLIENT_FORBIDDEN_KEYS = {
    "budget_total",
    "budget_spent",
    "timeline_health",
    "budget_health",
    "safety_health",
    "created_by",
    "completed_by",
    "archived_by",
    "restored_by",
    "archived_at",
    "restored_at",
    "created_at",
    "updated_at",
}

CLIENT_PRESENT_KEYS = {
    "id",
    "project_code",
    "name",
    "site_address",
    "client_name",
    "start_date",
    "target_end_date",
    "status",
    "percent_complete",
    "completed_at",
}

CLIENT_INVOICE_FORBIDDEN_KEYS = {
    "billing_milestone_id",
    "notes",
    "issued_by",
    "paid_by",
    "cancelled_by",
    "updated_at",
}


async def create_milestone(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, **overrides
):
    payload = {
        "name": "Foundation",
        "billing_type": "percentage",
        "billing_percentage": 20,
        "sort_order": 1,
        "description": "Ground floor + slab",
    }
    payload.update(overrides)
    return await client.post(
        f"/api/v1/projects/{project_id}/billing-milestones",
        headers={"Authorization": header},
        json=payload,
    )


async def complete_milestone(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, milestone_id: uuid.UUID
):
    return await client.post(
        f"/api/v1/projects/{project_id}/billing-milestones/{milestone_id}/complete",
        headers={"Authorization": header},
    )


async def make_invoice(
    client: httpx.AsyncClient,
    header: str,
    project_id: uuid.UUID,
    milestone_id: uuid.UUID,
    **overrides,
):
    payload = {"billing_milestone_id": str(milestone_id)}
    payload.update(overrides)
    return await client.post(
        f"/api/v1/projects/{project_id}/invoices",
        headers={"Authorization": header},
        json=payload,
    )


async def create_second_project(client: httpx.AsyncClient, header: str) -> uuid.UUID:
    resp = await client.post(
        "/api/v1/projects",
        headers={"Authorization": header},
        json={
            "name": "Other Site",
            "site_address": "456 Elsewhere Street",
            "client_name": "Other Co.",
            "start_date": "2026-02-01",
            "target_end_date": "2026-11-30",
            "budget_total": 500000,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- Project reads: the tight client shape ----------------------------------


@pytest.mark.asyncio
async def test_client_project_shape_list_and_detail(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")

    listing = await client.get("/api/v1/projects", headers={"Authorization": header})
    assert listing.status_code == 200
    (item,) = listing.json()
    assert CLIENT_PRESENT_KEYS <= set(item.keys())
    assert not (set(item.keys()) & CLIENT_FORBIDDEN_KEYS)

    one = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert one.status_code == 200
    assert CLIENT_PRESENT_KEYS <= set(one.json().keys())
    assert not (set(one.json().keys()) & CLIENT_FORBIDDEN_KEYS)


@pytest.mark.asyncio
async def test_client_only_own_projects_in_list(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    # A second project the client is NOT assigned to must never appear.
    admin = await auth_header(client, "admin@test.com")
    other_id = await create_second_project(client, admin)

    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")
    listing = await client.get("/api/v1/projects", headers={"Authorization": header})
    assert listing.status_code == 200
    ids = {p["id"] for p in listing.json()}
    assert ids == {str(test_project.id)}
    assert other_id not in ids


# --- Health is an internal management signal --------------------------------


@pytest.mark.asyncio
async def test_client_health_forbidden(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")

    rollup = await client.get("/api/v1/projects/health", headers={"Authorization": header})
    assert rollup.status_code == 403

    one = await client.get(
        f"/api/v1/projects/{test_project.id}/health", headers={"Authorization": header}
    )
    assert one.status_code == 403


# --- Inventory / procurement is an internal surface -------------------------


@pytest.mark.asyncio
async def test_client_inventory_403(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")
    created = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory",
        headers={"Authorization": admin},
        json={"name": "Cement", "unit": "bag", "unit_cost": 12.5, "opening_quantity": 100},
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    header = await auth_header(client, "client@test.com")
    items = await client.get(
        f"/api/v1/projects/{test_project.id}/inventory", headers={"Authorization": header}
    )
    assert items.status_code == 403

    movements = await client.get(
        f"/api/v1/projects/{test_project.id}/inventory/{item_id}/movements",
        headers={"Authorization": header},
    )
    assert movements.status_code == 403


# --- Invoices: issued only, restricted shape --------------------------------


@pytest.mark.asyncio
async def test_client_draft_invoice_hidden_and_sent_visible(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")

    m = (await create_milestone(client, admin, test_project.id)).json()
    await complete_milestone(client, admin, test_project.id, m["id"])
    draft = (await make_invoice(client, admin, test_project.id, m["id"])).json()
    assert draft["status"] == "draft"

    header = await auth_header(client, "client@test.com")
    # DRAFT is filtered out of the client's list...
    listing = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": header}
    )
    assert listing.status_code == 200
    assert listing.json() == []
    # ...and 404s on detail (existence never leaked).
    one = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices/{draft['id']}",
        headers={"Authorization": header},
    )
    assert one.status_code == 404

    # Issue -> SENT: now visible in the restricted client shape.
    issued = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{draft['id']}/issue",
        headers={"Authorization": admin},
    )
    assert issued.status_code == 200

    listing = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": header}
    )
    assert listing.status_code == 200
    (item,) = listing.json()
    assert item["status"] == "sent"
    assert item["overdue"] in (True, False)
    assert not (set(item.keys()) & CLIENT_INVOICE_FORBIDDEN_KEYS)

    one = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices/{draft['id']}",
        headers={"Authorization": header},
    )
    assert one.status_code == 200
    assert one.json()["status"] == "sent"


@pytest.mark.asyncio
async def test_client_cannot_see_unassigned_project_invoices(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    admin = await auth_header(client, "admin@test.com")
    other_id = await create_second_project(client, admin)
    # Client assigned only to the fixture project, not the second one.
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    header = await auth_header(client, "client@test.com")
    listing = await client.get(
        f"/api/v1/projects/{other_id}/invoices", headers={"Authorization": header}
    )
    assert listing.status_code == 403


# --- Clients are read-only in this phase ------------------------------------


@pytest.mark.asyncio
async def test_client_write_endpoints_403(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")

    task = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": header},
        json={"name": "Pour slab", "start_date": "2026-01-15", "end_date": "2026-01-20"},
    )
    assert task.status_code == 403

    milestone = await create_milestone(client, header, test_project.id)
    assert milestone.status_code == 403

    inventory = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory",
        headers={"Authorization": header},
        json={"name": "Cement", "unit": "bag"},
    )
    assert inventory.status_code == 403
