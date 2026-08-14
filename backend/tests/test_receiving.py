"""
M15 — PO delivery verification / receiving tests.

Covers the receiving API over the real ASGI client + real Postgres:
  * RBAC: admin + procurement receive; supervisor/client 403 on receive and on
    the deliveries read endpoints.
  * IDOR: cross-project PO line / inventory item -> 404.
  * Partial, full, multiple-receipt, exact-remaining-boundary, over-receiving,
    zero/negative quantity.
  * Invalid PO states (DRAFT/PENDING_APPROVAL/REJECTED/CANCELLED/RECEIVED) and
    invalid project states (COMPLETED 400 / ARCHIVED 403).
  * Unit mismatch + inventory-item linkage divergence.
  * Cancellation after receiving rejected.
  * Idempotency: replay verbatim, different-body 409, failed attempt frees the
    key for a safe retry.
  * Rollback: a failed receipt leaves no deliveries/stock/job-cost/budget/
    audit/notification rows.
  * Audit (po_receive) + notification (po_received) rows.
  * Inventory ledger + budget reconciliation after receipts.
  * Real separate-session concurrency: same-line and different-line races.
"""
import asyncio
import uuid
from datetime import date
from decimal import Decimal
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.delivery import Delivery
from app.models.finance import JobCost
from app.models.inventory import StockMovement
from app.models.notification import Notification
from app.models.project import Project, ProjectStatus
from app.models.user import User
from tests.conftest import TEST_DATABASE_URL, auth_header


def line_payload(**overrides):
    payload = {
        "description": "Cement",
        "quantity": 100,
        "unit": "bag",
        "unit_price": 350,
        "cost_code": "material",
    }
    payload.update(overrides)
    return payload


def po_payload(**overrides):
    payload = {"vendor_id": None, "order_date": "2026-08-01", "lines": [line_payload()]}
    payload.update(overrides)
    return payload


def receive_payload(lines, reference="DN-001", **overrides):
    payload = {"reference": reference, "lines": lines}
    payload.update(overrides)
    return payload


def receive_line(po_line_id, quantity, item_id):
    return {
        "po_line_id": str(po_line_id),
        "quantity": quantity,
        "inventory_item_id": str(item_id),
    }


async def make_vendor(client: httpx.AsyncClient, header: str, name: str = "Cement Co") -> dict:
    resp = await client.post(
        "/api/v1/vendors",
        headers={"Authorization": header},
        json={"name": name, "email": f"{name.lower().replace(' ', '')}@example.com"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def create_po(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, **overrides
) -> httpx.Response:
    payload = po_payload(**overrides)
    assert payload["vendor_id"] is not None, "vendor_id must be set"
    return await client.post(
        f"/api/v1/projects/{project_id}/purchase-orders",
        headers={"Authorization": header},
        json=payload,
    )


async def make_item(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, name: str = "Cement", unit: str = "bag"
) -> dict:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/inventory",
        headers={"Authorization": header},
        json={"name": name, "unit": unit},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def get_item(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, item_id: str
) -> dict:
    """The inventory API has no single-item GET — read via the list endpoint."""
    resp = await client.get(
        f"/api/v1/projects/{project_id}/inventory", headers={"Authorization": header}
    )
    assert resp.status_code == 200, resp.text
    return next(i for i in resp.json() if i["id"] == item_id)


async def make_approved_po(
    client: httpx.AsyncClient,
    header: str,
    project_id: uuid.UUID,
    vendor_name: str = "Cement Co",
    **overrides,
) -> dict:
    vendor = await make_vendor(client, header, name=vendor_name)
    resp = await create_po(client, header, project_id, vendor_id=vendor["id"], **overrides)
    assert resp.status_code == 201, resp.text
    po = resp.json()
    url = f"/api/v1/projects/{project_id}/purchase-orders/{po['id']}"
    assert (await client.post(f"{url}/submit", headers={"Authorization": header})).status_code == 200
    assert (await client.post(f"{url}/approve", headers={"Authorization": header})).status_code == 200
    return (await client.get(url, headers={"Authorization": header})).json()


async def receive(
    client: httpx.AsyncClient,
    header: str,
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    payload: dict,
    idempotency_key: str | None = None,
) -> httpx.Response:
    headers = {"Authorization": header}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return await client.post(
        f"/api/v1/projects/{project_id}/purchase-orders/{po_id}/receive",
        headers=headers,
        json=payload,
    )


async def audit_actions_for(
    db: AsyncSession, action: str, record_id: str | None = None
) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.action == action)
    if record_id is not None:
        stmt = stmt.where(AuditLog.record_id == record_id)
    return list((await db.execute(stmt)).scalars().all())


async def count_rows(db: AsyncSession, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


# --- RBAC ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_and_procurement_can_receive(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_procurement_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    proc = await auth_header(client, "procurement@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    payload = receive_payload([receive_line(line["id"], 40, item["id"])])
    for header in (admin, proc):
        resp = await receive(client, header, test_project.id, po["id"], payload)
        assert resp.status_code == 201, resp.text
        assert resp.json()["po_status_after"] == "partially_received"


@pytest.mark.asyncio
async def test_supervisor_and_client_403(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_supervisor_user: User,
    test_client_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]
    payload = receive_payload([receive_line(line["id"], 10, item["id"])])
    po_url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"

    sup = await auth_header(client, "supervisor@test.com")
    cli = await auth_header(client, "client@test.com")
    for header in (sup, cli):
        resp = await receive(client, header, test_project.id, po["id"], payload)
        assert resp.status_code == 403, resp.text
        assert (await client.get(f"{po_url}/deliveries", headers={"Authorization": header})).status_code == 403
        assert (await client.get(f"{po_url}/deliveries/00000000-0000-0000-0000-000000000000", headers={"Authorization": header})).status_code == 403


# --- IDOR ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_project_line_and_item_404(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    other = Project(
        project_code="PRJ-TEST-0002",
        name="Other Residence",
        site_address="999 Other St",
        client_name="Other Co.",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        budget_total=1000000,
    )
    test_db.add(other)
    await test_db.commit()
    await test_db.refresh(other)

    admin = await auth_header(client, "admin@test.com")
    item_a = await make_item(client, admin, test_project.id)
    po_a = await make_approved_po(client, admin, test_project.id)
    line_a = po_a["lines"][0]

    item_b = await make_item(client, admin, other.id, name="Bricks", unit="pcs")
    po_b = await make_approved_po(
        client, admin, other.id, vendor_name="Bricks Co",
        lines=[line_payload(description="Bricks", unit="pcs")],
    )
    line_b = po_b["lines"][0]

    # Other project's PO line -> 404.
    resp = await receive(
        client, admin, test_project.id, po_a["id"],
        receive_payload([receive_line(line_b["id"], 10, item_a["id"])]),
    )
    assert resp.status_code == 404, resp.text
    # Other project's inventory item -> 404.
    resp = await receive(
        client, admin, test_project.id, po_a["id"],
        receive_payload([receive_line(line_a["id"], 10, item_b["id"])]),
    )
    assert resp.status_code == 404, resp.text
    # Nothing was received.
    assert await count_rows(test_db, Delivery) == 0


# --- Partial / full / multiple receipts ---------------------------------------


@pytest.mark.asyncio
async def test_partial_receipt_releases_verified_line_only(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    cement_item = await make_item(client, admin, test_project.id, name="Cement", unit="bag")
    brick_item = await make_item(client, admin, test_project.id, name="Bricks", unit="pcs")
    po = await make_approved_po(
        client,
        admin,
        test_project.id,
        lines=[
            line_payload(description="Cement", quantity=100, unit="bag", unit_price=350),
            line_payload(description="Bricks", quantity=50, unit="pcs", unit_price=20, cost_code="masonry"),
        ],
    )
    cement_line, brick_line = po["lines"]

    resp = await receive(
        client, admin, test_project.id, po["id"],
        receive_payload([receive_line(cement_line["id"], 40, cement_item["id"])]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["po_status_after"] == "partially_received"
    assert resp.json()["line_count"] == 1

    po_after = (
        await client.get(
            f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}",
            headers={"Authorization": admin},
        )
    ).json()
    assert po_after["status"] == "partially_received"
    cement_after = next(line for line in po_after["lines"] if line["id"] == cement_line["id"])
    brick_after = next(line for line in po_after["lines"] if line["id"] == brick_line["id"])
    assert cement_after["received_quantity"] == 40.0
    assert cement_after["received_remaining"] == 60.0
    assert brick_after["received_quantity"] == 0.0  # unverified line untouched
    assert brick_after["received_remaining"] == 50.0

    # Stock released only for the verified line.
    cement = await get_item(client, admin, test_project.id, cement_item["id"])
    assert cement["quantity_on_hand"] == 40.0
    brick = await get_item(client, admin, test_project.id, brick_item["id"])
    assert brick["quantity_on_hand"] == 0.0

    # Cost released only for the verified line (40 x 350 = 14000).
    costs = (
        await client.get(
            f"/api/v1/projects/{test_project.id}/job-costs", headers={"Authorization": admin}
        )
    ).json()
    assert len(costs) == 1
    assert float(costs[0]["amount"]) == 14000.0
    assert costs[0]["cost_code"] == "material"


@pytest.mark.asyncio
async def test_full_receipt_sets_received_terminal(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    resp = await receive(
        client, admin, test_project.id, po["id"],
        receive_payload([receive_line(line["id"], 100, item["id"])]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["po_status_after"] == "received"

    po_after = (
        await client.get(
            f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}",
            headers={"Authorization": admin},
        )
    ).json()
    assert po_after["status"] == "received"
    assert po_after["lines"][0]["received_quantity"] == 100.0

    # RECEIVED is terminal — further receive is a no-op 400.
    resp = await receive(
        client, admin, test_project.id, po["id"],
        receive_payload([receive_line(line["id"], 1, item["id"])]),
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_multiple_receipts_accumulate(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    first = await receive(
        client, admin, test_project.id, po["id"],
        receive_payload([receive_line(line["id"], 40, item["id"])], reference="DN-001"),
    )
    assert first.status_code == 201 and first.json()["po_status_after"] == "partially_received"
    second = await receive(
        client, admin, test_project.id, po["id"],
        receive_payload([receive_line(line["id"], 60, item["id"])], reference="DN-002"),
    )
    assert second.status_code == 201 and second.json()["po_status_after"] == "received"

    po_after = (
        await client.get(
            f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}",
            headers={"Authorization": admin},
        )
    ).json()
    assert po_after["status"] == "received"
    assert po_after["lines"][0]["received_quantity"] == 100.0

    deliveries = (
        await client.get(
            f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/deliveries",
            headers={"Authorization": admin},
        )
    ).json()
    assert len(deliveries) == 2
    assert deliveries[0]["reference"] == "DN-002"  # newest first
    assert {d["line_count"] for d in deliveries} == {1}

    detail = (
        await client.get(
            f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/deliveries/{second.json()['id']}",
            headers={"Authorization": admin},
        )
    ).json()
    assert len(detail["lines"]) == 1
    assert detail["lines"][0]["description"] == "Cement"
    assert detail["lines"][0]["quantity_received"] == 60.0
    assert detail["lines"][0]["line_total"] == 21000.0  # 60 x 350

    item_after = await get_item(client, admin, test_project.id, item["id"])
    assert item_after["quantity_on_hand"] == 100.0
    assert await count_rows(test_db, StockMovement) == 2
    assert await count_rows(test_db, JobCost) == 2


# --- Boundaries / over-receiving ----------------------------------------------


@pytest.mark.asyncio
async def test_exact_remaining_boundary_allowed_then_rejected(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id, lines=[line_payload(quantity=100)])
    line = po["lines"][0]

    # 60 of 100 -> remaining 40.
    assert (await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 60, item["id"])]))).status_code == 201
    # Exactly the remaining 40 -> ok, and now fully received.
    resp = await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 40, item["id"])]))
    assert resp.status_code == 201 and resp.json()["po_status_after"] == "received"
    # Any further positive quantity is a no-op -> 400.
    resp = await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 0.01, item["id"])]))
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_over_receiving_rejected(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id, lines=[line_payload(quantity=100)])
    line = po["lines"][0]

    resp = await receive(
        client, admin, test_project.id, po["id"],
        receive_payload([receive_line(line["id"], 100.01, item["id"])]),
    )
    assert resp.status_code == 400, resp.text
    assert "over-receive" in resp.json()["detail"]

    # A single request that repeats the same line must not bypass the guard.
    resp = await receive(
        client, admin, test_project.id, po["id"],
        receive_payload([receive_line(line["id"], 60, item["id"]), receive_line(line["id"], 60, item["id"])]),
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_zero_or_negative_quantity_422(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    for qty in (0, -5):
        resp = await receive(
            client, admin, test_project.id, po["id"],
            receive_payload([receive_line(line["id"], qty, item["id"])]),
        )
        assert resp.status_code == 422, resp.text


# --- Invalid PO / project states ----------------------------------------------


@pytest.mark.asyncio
async def test_invalid_po_states_rejected(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    vendor = await make_vendor(client, admin)

    # DRAFT.
    draft = (await create_po(client, admin, test_project.id, vendor_id=vendor["id"])).json()
    line = draft["lines"][0]
    resp = await receive(client, admin, test_project.id, draft["id"], receive_payload([receive_line(line["id"], 10, item["id"])]))
    assert resp.status_code == 400, resp.text

    # PENDING_APPROVAL.
    pending = (await create_po(client, admin, test_project.id, vendor_id=vendor["id"])).json()
    line = pending["lines"][0]
    await client.post(f"/api/v1/projects/{test_project.id}/purchase-orders/{pending['id']}/submit", headers={"Authorization": admin})
    resp = await receive(client, admin, test_project.id, pending["id"], receive_payload([receive_line(line["id"], 10, item["id"])]))
    assert resp.status_code == 400, resp.text

    # REJECTED.
    rejected = (await create_po(client, admin, test_project.id, vendor_id=vendor["id"])).json()
    line = rejected["lines"][0]
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{rejected['id']}"
    await client.post(f"{url}/submit", headers={"Authorization": admin})
    await client.post(f"{url}/reject", headers={"Authorization": admin}, json={"rejected_reason": "nope"})
    resp = await receive(client, admin, test_project.id, rejected["id"], receive_payload([receive_line(line["id"], 10, item["id"])]))
    assert resp.status_code == 400, resp.text

    # CANCELLED.
    cancelled = (await create_po(client, admin, test_project.id, vendor_id=vendor["id"])).json()
    line = cancelled["lines"][0]
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{cancelled['id']}"
    await client.post(f"{url}/cancel", headers={"Authorization": admin})
    resp = await receive(client, admin, test_project.id, cancelled["id"], receive_payload([receive_line(line["id"], 10, item["id"])]))
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_completed_project_frozen_400(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    assert (await client.post(f"/api/v1/projects/{test_project.id}/complete", headers={"Authorization": admin})).status_code == 200
    resp = await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 10, item["id"])]))
    assert resp.status_code == 400, resp.text
    assert await count_rows(test_db, Delivery) == 0


@pytest.mark.asyncio
async def test_archived_project_read_only_403(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    assert (await client.post(f"/api/v1/projects/{test_project.id}/archive", headers={"Authorization": admin})).status_code == 200
    resp = await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 10, item["id"])]))
    assert resp.status_code == 403, resp.text
    # A/P reads remain.
    assert (await client.get(f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/deliveries", headers={"Authorization": admin})).status_code == 200


# --- Unit / linkage guards ----------------------------------------------------


@pytest.mark.asyncio
async def test_unit_mismatch_rejected(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id, name="Cement", unit="kg")
    po = await make_approved_po(client, admin, test_project.id)  # line unit is "bag"
    line = po["lines"][0]

    resp = await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 10, item["id"])]))
    assert resp.status_code == 400, resp.text
    assert "Unit mismatch" in resp.json()["detail"]
    assert await count_rows(test_db, Delivery) == 0


@pytest.mark.asyncio
async def test_inventory_item_linkage_is_immutable(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item_a = await make_item(client, admin, test_project.id, name="Cement A", unit="bag")
    item_b = await make_item(client, admin, test_project.id, name="Cement B", unit="bag")
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    resp = await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 40, item_a["id"])]))
    assert resp.status_code == 201, resp.text

    # Same PO line must keep receiving into the same item.
    resp = await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 10, item_b["id"])]))
    assert resp.status_code == 400, resp.text
    assert "already linked to a different inventory item" in resp.json()["detail"]


# --- Cancellation after receiving ---------------------------------------------


@pytest.mark.asyncio
async def test_cancel_rejected_after_receiving(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"

    await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 40, item["id"])]))
    resp = await client.post(f"{url}/cancel", headers={"Authorization": admin})
    assert resp.status_code == 400, resp.text
    assert "has received stock" in resp.json()["detail"]

    # Fully received is also not cancellable.
    await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 60, item["id"])]))
    resp = await client.post(f"{url}/cancel", headers={"Authorization": admin})
    assert resp.status_code == 400, resp.text


# --- Idempotency --------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_receive_replays(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]
    payload = receive_payload([receive_line(line["id"], 40, item["id"])])

    first = await receive(client, admin, test_project.id, po["id"], payload, idempotency_key="key-receive-001")
    assert first.status_code == 201, first.text
    replay = await receive(client, admin, test_project.id, po["id"], payload, idempotency_key="key-receive-001")
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["po_status_after"] == first.json()["po_status_after"]

    # Exactly one receipt / stock movement / job cost.
    assert await count_rows(test_db, Delivery) == 1
    assert await count_rows(test_db, StockMovement) == 1
    assert await count_rows(test_db, JobCost) == 1
    item_after = await get_item(client, admin, test_project.id, item["id"])
    assert item_after["quantity_on_hand"] == 40.0


@pytest.mark.asyncio
async def test_idempotent_receive_different_body_409(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    payload = receive_payload([receive_line(line["id"], 40, item["id"])])
    assert (await receive(client, admin, test_project.id, po["id"], payload, idempotency_key="key-receive-002")).status_code == 201
    different = receive_payload([receive_line(line["id"], 50, item["id"])])
    resp = await receive(client, admin, test_project.id, po["id"], different, idempotency_key="key-receive-002")
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_failed_receive_frees_idempotency_key(
    concurrent_client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    """A failed attempt rolls the claim back, so the key stays free for a safe
    retry. Uses per-request sessions (the M8 doctrine) because the failed
    request must tear its transaction down before the retry runs."""
    header = await auth_header(concurrent_client, "admin@test.com")
    item = await make_item(concurrent_client, header, test_project.id)
    po = await make_approved_po(
        concurrent_client, header, test_project.id, lines=[line_payload(quantity=100)]
    )
    line = po["lines"][0]

    over = receive_payload([receive_line(line["id"], 101, item["id"])])
    resp = await receive(
        concurrent_client, header, test_project.id, po["id"], over, idempotency_key="key-receive-003"
    )
    assert resp.status_code == 400, resp.text

    good = receive_payload([receive_line(line["id"], 40, item["id"])])
    retry = await receive(
        concurrent_client, header, test_project.id, po["id"], good, idempotency_key="key-receive-003"
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["po_status_after"] == "partially_received"


# --- Rollback -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_receipt_rolls_back_everything(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    """A receipt that fails mid-request (valid first line, over-receiving second)
    leaves zero rows: no deliveries/lines, no stock, no job costs, no budget
    change, no audit, no notification — and the key stays free."""
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id, name="Cement", unit="bag")
    other_item = await make_item(client, admin, test_project.id, name="Sand", unit="bag")
    po = await make_approved_po(
        client, admin, test_project.id,
        lines=[
            line_payload(description="Cement", quantity=100, unit="bag", unit_price=350),
            line_payload(description="Sand", quantity=50, unit="bag", unit_price=10),
        ],
    )
    cement_line, sand_line = po["lines"]
    budget_before = (await client.get(f"/api/v1/projects/{test_project.id}/budget", headers={"Authorization": admin})).json()["budget_spent"]

    payload = receive_payload(
        [receive_line(cement_line["id"], 40, item["id"]), receive_line(sand_line["id"], 60, other_item["id"])]
    )
    resp = await receive(client, admin, test_project.id, po["id"], payload, idempotency_key="key-receive-004")
    assert resp.status_code == 400, resp.text

    assert await count_rows(test_db, Delivery) == 0
    assert await count_rows(test_db, StockMovement) == 0
    assert await count_rows(test_db, JobCost) == 0
    assert await audit_actions_for(test_db, "po_receive") == []
    notifications = (
        await test_db.execute(select(func.count()).select_from(Notification).where(Notification.type == "po_received"))
    ).scalar_one()
    assert notifications == 0
    for item_id in (item["id"], other_item["id"]):
        cur = await get_item(client, admin, test_project.id, item_id)
        assert cur["quantity_on_hand"] == 0.0
    budget_after = (await client.get(f"/api/v1/projects/{test_project.id}/budget", headers={"Authorization": admin})).json()["budget_spent"]
    assert budget_after == budget_before


# --- Audit + notifications + reconciliation -----------------------------------


@pytest.mark.asyncio
async def test_audit_and_notification_rows_created(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    resp = await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 40, item["id"])]))
    assert resp.status_code == 201, resp.text

    rows = await audit_actions_for(test_db, "po_receive", resp.json()["id"])
    assert len(rows) == 1
    changes = rows[0].changes
    assert changes["po_number"] == {"old": None, "new": po["po_number"]}
    assert changes["status"] == {"old": "approved", "new": "partially_received"}
    assert changes["received_total"] == {"old": None, "new": 14000.0}

    notif = (
        await test_db.execute(
            select(Notification).where(
                Notification.type == "po_received", Notification.user_id == test_admin_user.id
            )
        )
    ).scalars().all()
    assert len(notif) == 1
    assert notif[0].title == "Purchase order partially received"

    # No supervisor/client receives po_received (no supervisor/client exists to
    # receive it; recipients are PO creator + active admins).
    assert (
        await test_db.execute(
            select(func.count()).select_from(Notification).where(Notification.type == "po_received")
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_receipt_updates_inventory_and_budget_reconciliation(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    item = await make_item(client, admin, test_project.id)
    po = await make_approved_po(client, admin, test_project.id)
    line = po["lines"][0]

    await receive(client, admin, test_project.id, po["id"], receive_payload([receive_line(line["id"], 40, item["id"])]))

    recon = (await client.get(f"/api/v1/projects/{test_project.id}/inventory/reconciliation", headers={"Authorization": admin})).json()
    row = next(r for r in recon if r["item_id"] == item["id"])
    assert row["quantity_on_hand"] == row["ledger_balance"] == 40.0
    assert row["matches"] is True

    movements = (await client.get(f"/api/v1/projects/{test_project.id}/inventory/{item['id']}/movements", headers={"Authorization": admin})).json()
    assert len(movements) == 1
    assert movements[0]["movement_type"] == "received"
    assert movements[0]["quantity"] == 40.0
    assert movements[0]["po_line_id"] == line["id"]

    costs = (await client.get(f"/api/v1/projects/{test_project.id}/job-costs", headers={"Authorization": admin})).json()
    assert len(costs) == 1
    assert costs[0]["po_line_id"] == line["id"]
    assert costs[0]["cost_code"] == "material"

    budget = (await client.get(f"/api/v1/projects/{test_project.id}/budget", headers={"Authorization": admin})).json()
    assert budget["budget_spent"] == 14000.0
    assert Decimal(str(budget["budget_spent"])) == Decimal(str(budget["by_cost_code"]["material"]))


# --- Concurrency (real separate DB sessions) ----------------------------------


@pytest.fixture
async def concurrent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Per-request DB session so concurrent requests race for real."""
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
async def test_concurrent_same_line_serializes_no_over_receipt(
    concurrent_client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    """Two concurrent receipts against the same PO line serialize on the
    project+PO locks: both apply (40+40) and received_quantity can never exceed
    the ordered quantity."""
    header = await auth_header(concurrent_client, "admin@test.com")
    item = await make_item(concurrent_client, header, test_project.id)
    po = await make_approved_po(concurrent_client, header, test_project.id, lines=[line_payload(quantity=100)])
    line = po["lines"][0]
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/receive"

    async def send() -> httpx.Response:
        return await concurrent_client.post(
            url,
            headers={"Authorization": header},
            json=receive_payload([receive_line(line["id"], 40, item["id"])]),
        )

    responses = await asyncio.gather(send(), send())
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]

    po_after = (await concurrent_client.get(f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}", headers={"Authorization": header})).json()
    assert po_after["lines"][0]["received_quantity"] == 80.0
    assert po_after["status"] == "partially_received"
    assert await count_rows(test_db, Delivery) == 2


@pytest.mark.asyncio
async def test_concurrent_same_line_over_receipt_rejected(
    concurrent_client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    """Two concurrent 60-unit receipts on a 100-unit line: the project lock
    serializes them, the second sees the updated received_quantity and is
    rejected — exactly one receipt, no over-receiving."""
    header = await auth_header(concurrent_client, "admin@test.com")
    item = await make_item(concurrent_client, header, test_project.id)
    po = await make_approved_po(concurrent_client, header, test_project.id, lines=[line_payload(quantity=100)])
    line = po["lines"][0]
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/receive"

    async def send() -> httpx.Response:
        return await concurrent_client.post(
            url,
            headers={"Authorization": header},
            json=receive_payload([receive_line(line["id"], 60, item["id"])]),
        )

    responses = await asyncio.gather(send(), send())
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 400], [r.text for r in responses]

    po_after = (await concurrent_client.get(f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}", headers={"Authorization": header})).json()
    assert po_after["lines"][0]["received_quantity"] == 60.0
    assert await count_rows(test_db, Delivery) == 1


@pytest.mark.asyncio
async def test_concurrent_different_lines_both_apply(
    concurrent_client: httpx.AsyncClient,
    test_admin_user: User,
    test_db: AsyncSession,
    test_project: Project,
):
    header = await auth_header(concurrent_client, "admin@test.com")
    cement = await make_item(concurrent_client, header, test_project.id, name="Cement", unit="bag")
    brick = await make_item(concurrent_client, header, test_project.id, name="Bricks", unit="pcs")
    po = await make_approved_po(
        concurrent_client, header, test_project.id,
        lines=[
            line_payload(description="Cement", quantity=100, unit="bag", unit_price=350),
            line_payload(description="Bricks", quantity=50, unit="pcs", unit_price=20, cost_code="masonry"),
        ],
    )
    cement_line, brick_line = po["lines"]
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/receive"

    async def send_cement() -> httpx.Response:
        return await concurrent_client.post(
            url,
            headers={"Authorization": header},
            json=receive_payload([receive_line(cement_line["id"], 40, cement["id"])]),
        )

    async def send_brick() -> httpx.Response:
        return await concurrent_client.post(
            url,
            headers={"Authorization": header},
            json=receive_payload([receive_line(brick_line["id"], 50, brick["id"])]),
        )

    responses = await asyncio.gather(send_cement(), send_brick())
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]

    po_after = (await concurrent_client.get(f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}", headers={"Authorization": header})).json()
    by_id = {line["id"]: line for line in po_after["lines"]}
    assert by_id[cement_line["id"]]["received_quantity"] == 40.0
    assert by_id[brick_line["id"]]["received_quantity"] == 50.0
    assert po_after["status"] == "partially_received"
    assert await count_rows(test_db, Delivery) == 2
