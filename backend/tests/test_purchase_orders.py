"""
M14 — purchase-order tests.

Covers the PO domain over the real ASGI client:
  * po_number format + per-project sequencing.
  * Line ops (add/update/delete) with the total == SUM(line_total) + tax
    invariant recomputed on every mutation.
  * The full DRAFT -> PENDING_APPROVAL -> APPROVED / REJECTED -> revise /
    resubmit / cancel state machine incl. illegal moves (400/422).
  * RBAC matrix (§10): approve/reject admin-only; procurement 403 on those;
    S/C 403 on every route.
  * Lifecycle gating: COMPLETED frozen (400), ARCHIVED read-only (403), reads
    OK for A/P.
  * Idempotency: create-PO and add-line replay verbatim; different-body 409.
  * IDOR: cross-project PO/line -> 404.
  * Audit rows per action.
  * Real two-session concurrency: distinct po_numbers, single same-key create,
    total never drifting under concurrent line adds.
"""
import asyncio
import re
import uuid
from datetime import date
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.idempotency import IdempotencyRecord
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
    payload = {
        "vendor_id": None,  # set by helper once a vendor exists
        "order_date": "2026-08-01",
        "lines": [line_payload()],
    }
    payload.update(overrides)
    return payload


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


async def add_line(
    client: httpx.AsyncClient,
    header: str,
    project_id: uuid.UUID,
    po_id: uuid.UUID,
    **overrides,
) -> httpx.Response:
    return await client.post(
        f"/api/v1/projects/{project_id}/purchase-orders/{po_id}/lines",
        headers={"Authorization": header},
        json=line_payload(**overrides),
    )


async def get_po(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, po_id: uuid.UUID
) -> dict:
    resp = await client.get(
        f"/api/v1/projects/{project_id}/purchase-orders/{po_id}",
        headers={"Authorization": header},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def audit_actions_for(
    db: AsyncSession, action: str, record_id: str | None = None
) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.action == action)
    if record_id is not None:
        stmt = stmt.where(AuditLog.record_id == record_id)
    return list((await db.execute(stmt)).scalars().all())


# --- Create + numbering + totals ----------------------------------------------


@pytest.mark.asyncio
async def test_create_po_with_nested_lines_and_numbering(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    resp = await create_po(
        client,
        header,
        test_project.id,
        vendor_id=vendor["id"],
        lines=[line_payload(quantity=10, unit_price=100), line_payload(quantity=5, unit_price=200, cost_code="labor")],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert re.fullmatch(r"PO-PRJ-TEST-0001-0001", body["po_number"])
    assert body["status"] == "draft"
    assert body["project_code"] == "PRJ-TEST-0001"
    assert body["vendor_name"] == "Cement Co"
    assert body["subtotal"] == 2000.0
    assert body["tax_amount"] == 0.0
    assert body["total_amount"] == 2000.0
    assert len(body["lines"]) == 2
    assert body["lines"][0]["line_total"] == 1000.0
    assert body["lines"][1]["line_total"] == 1000.0


@pytest.mark.asyncio
async def test_po_number_sequences_per_project(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    first = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    second = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    assert first["po_number"] == "PO-PRJ-TEST-0001-0001"
    assert second["po_number"] == "PO-PRJ-TEST-0001-0002"

    other = Project(
        project_code="PRJ-2026-0002",
        name="Other Residence",
        site_address="1 Other St",
        client_name="Other Co",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        budget_total=100000,
    )
    test_db.add(other)
    await test_db.commit()
    await test_db.refresh(other)
    third = (await create_po(client, header, other.id, vendor_id=vendor["id"])).json()
    assert third["po_number"] == "PO-PRJ-2026-0002-0001"


@pytest.mark.asyncio
async def test_total_includes_tax(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    body = (
        await create_po(
            client,
            header,
            test_project.id,
            vendor_id=vendor["id"],
            tax_rate=18,
            lines=[line_payload(quantity=2, unit_price=50)],
        )
    ).json()
    assert body["subtotal"] == 100.0
    assert body["tax_amount"] == 18.0
    assert body["total_amount"] == 118.0


@pytest.mark.asyncio
async def test_line_total_rounds_half_up(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    """unit_price 0.335 x qty 1 = 0.335 -> ROUND_HALF_UP -> 0.34 (never 0.33)."""
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    body = (
        await create_po(
            client,
            header,
            test_project.id,
            vendor_id=vendor["id"],
            lines=[line_payload(quantity=1, unit_price=0.335)],
        )
    ).json()
    assert body["lines"][0]["line_total"] == 0.34
    assert body["subtotal"] == 0.34
    assert body["total_amount"] == 0.34


@pytest.mark.asyncio
async def test_vendor_must_be_active(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    await client.patch(
        f"/api/v1/vendors/{vendor['id']}", headers={"Authorization": header}, json={"is_active": False}
    )
    resp = await create_po(client, header, test_project.id, vendor_id=vendor["id"])
    assert resp.status_code == 400
    assert "deactivated" in resp.json()["detail"]


# --- Line operations -----------------------------------------------------------


@pytest.mark.asyncio
async def test_add_edit_delete_line_recomputes_total(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    assert po["total_amount"] == 35000.0  # 100 x 350

    added = (
        await add_line(
            client, header, test_project.id, po["id"],
            description="Steel", quantity=10, unit_price=1000, cost_code="structure",
        )
    ).json()
    assert added["line_total"] == 10000.0
    after_add = await get_po(client, header, test_project.id, po["id"])
    assert after_add["total_amount"] == 45000.0

    edited = (await client.patch(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines/{added['id']}",
        headers={"Authorization": header},
        json={"quantity": 20},
    )).json()
    assert edited["line_total"] == 20000.0
    after_edit = await get_po(client, header, test_project.id, po["id"])
    assert after_edit["total_amount"] == 55000.0

    deleted = await client.delete(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines/{added['id']}",
        headers={"Authorization": header},
    )
    assert deleted.status_code == 204
    after_delete = await get_po(client, header, test_project.id, po["id"])
    assert after_delete["total_amount"] == 35000.0


@pytest.mark.asyncio
async def test_line_ops_blocked_on_non_draft(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    line = po["lines"][0]
    await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/submit",
        headers={"Authorization": header},
    )

    add = await add_line(client, header, test_project.id, po["id"], description="Late")
    assert add.status_code == 400
    patch = await client.patch(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines/{line['id']}",
        headers={"Authorization": header},
        json={"quantity": 5},
    )
    assert patch.status_code == 400
    delete = await client.delete(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines/{line['id']}",
        headers={"Authorization": header},
    )
    assert delete.status_code == 400


@pytest.mark.asyncio
async def test_header_patch_on_draft(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()

    updated = (await client.patch(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}",
        headers={"Authorization": header},
        json={"tax_rate": 10, "notes": "rush order"},
    )).json()
    assert updated["tax_rate"] == 10.0
    assert updated["notes"] == "rush order"
    # 35000 subtotal + 10% tax.
    assert updated["total_amount"] == 38500.0

    # Clearing the tax rate recomputes without tax.
    cleared = (await client.patch(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}",
        headers={"Authorization": header},
        json={"tax_rate": None},
    )).json()
    assert cleared["tax_rate"] is None
    assert cleared["total_amount"] == 35000.0


@pytest.mark.asyncio
async def test_header_patch_blocked_on_non_draft(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/submit",
        headers={"Authorization": header},
    )
    resp = await client.patch(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}",
        headers={"Authorization": header},
        json={"notes": "nope"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_po_and_line_404(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    assert (await client.get(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{uuid.uuid4()}",
        headers={"Authorization": header},
    )).status_code == 404
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    resp = await client.patch(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines/{uuid.uuid4()}",
        headers={"Authorization": header},
        json={"quantity": 5},
    )
    assert resp.status_code == 404
    assert (await client.delete(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines/{uuid.uuid4()}",
        headers={"Authorization": header},
    )).status_code == 404


# --- State machine -------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_approval_cycle(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()

    submitted = (await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/submit",
        headers={"Authorization": header},
    )).json()
    assert submitted["status"] == "pending_approval"
    assert submitted["submitted_by"] == str(test_admin_user.id)

    approved = (await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/approve",
        headers={"Authorization": header},
    )).json()
    assert approved["status"] == "approved"
    assert approved["approved_by"] == str(test_admin_user.id)


@pytest.mark.asyncio
async def test_submit_requires_at_least_one_line(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"], lines=[])).json()
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/submit",
        headers={"Authorization": header},
    )
    assert resp.status_code == 400
    assert "at least one line" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_illegal_transitions(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"

    # approve/reject before submit -> 400.
    assert (await client.post(f"{url}/approve", headers={"Authorization": header})).status_code == 400
    assert (await client.post(f"{url}/reject", headers={"Authorization": header}, json={"rejected_reason": "no"})).status_code == 400
    # revise/resubmit on a DRAFT -> 400.
    assert (await client.post(f"{url}/revise", headers={"Authorization": header})).status_code == 400
    assert (await client.post(f"{url}/resubmit", headers={"Authorization": header})).status_code == 400

    await client.post(f"{url}/submit", headers={"Authorization": header})
    # Double submit -> 400.
    assert (await client.post(f"{url}/submit", headers={"Authorization": header})).status_code == 400

    await client.post(f"{url}/approve", headers={"Authorization": header})
    # approve of already-approved -> 400; submit of approved -> 400.
    assert (await client.post(f"{url}/approve", headers={"Authorization": header})).status_code == 400
    assert (await client.post(f"{url}/submit", headers={"Authorization": header})).status_code == 400


@pytest.mark.asyncio
async def test_reject_requires_reason(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/submit",
        headers={"Authorization": header},
    )
    missing = await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/reject",
        headers={"Authorization": header},
        json={},
    )
    assert missing.status_code == 422
    empty = await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/reject",
        headers={"Authorization": header},
        json={"rejected_reason": ""},
    )
    assert empty.status_code == 422


@pytest.mark.asyncio
async def test_reject_revise_resubmit_cycle(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"

    await client.post(f"{url}/submit", headers={"Authorization": header})
    rejected = (await client.post(
        f"{url}/reject", headers={"Authorization": header}, json={"rejected_reason": "price too high"}
    )).json()
    assert rejected["status"] == "rejected"
    assert rejected["rejected_reason"] == "price too high"

    revised = (await client.post(f"{url}/revise", headers={"Authorization": header})).json()
    assert revised["status"] == "draft"

    # Edit a line after revise, then submit again (revise returns to DRAFT).
    line = revised["lines"][0]
    await client.patch(
        f"{url}/lines/{line['id']}", headers={"Authorization": header}, json={"unit_price": 300}
    )
    resubmitted = (await client.post(f"{url}/submit", headers={"Authorization": header})).json()
    assert resubmitted["status"] == "pending_approval"

    approved = (await client.post(f"{url}/approve", headers={"Authorization": header})).json()
    assert approved["status"] == "approved"


@pytest.mark.asyncio
async def test_resubmit_directly_from_rejected(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    """resubmit moves REJECTED -> PENDING_APPROVAL without an edit pass."""
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"

    await client.post(f"{url}/submit", headers={"Authorization": header})
    await client.post(
        f"{url}/reject", headers={"Authorization": header}, json={"rejected_reason": "revise later"}
    )
    resubmitted = (await client.post(f"{url}/resubmit", headers={"Authorization": header})).json()
    assert resubmitted["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_cancel_terminal_and_rules(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)

    # Cancel a DRAFT.
    draft = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    cancelled = (await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{draft['id']}/cancel",
        headers={"Authorization": header},
    )).json()
    assert cancelled["status"] == "cancelled"
    # Terminal: no further transitions.
    assert (await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{draft['id']}/submit",
        headers={"Authorization": header},
    )).status_code == 400
    assert (await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{draft['id']}/cancel",
        headers={"Authorization": header},
    )).status_code == 400

    # Cancel a REJECTED PO is illegal.
    rej = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{rej['id']}/submit",
        headers={"Authorization": header},
    )
    await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{rej['id']}/reject",
        headers={"Authorization": header}, json={"rejected_reason": "nope"},
    )
    assert (await client.post(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{rej['id']}/cancel",
        headers={"Authorization": header},
    )).status_code == 400


# --- RBAC ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_reject_admin_only(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_procurement_user: User,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, admin)
    po = (await create_po(client, admin, test_project.id, vendor_id=vendor["id"])).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"
    await client.post(f"{url}/submit", headers={"Authorization": admin})

    proc = await auth_header(client, "procurement@test.com")
    assert (await client.post(f"{url}/approve", headers={"Authorization": proc})).status_code == 403
    assert (await client.post(
        f"{url}/reject", headers={"Authorization": proc}, json={"rejected_reason": "x"}
    )).status_code == 403


@pytest.mark.asyncio
async def test_procurement_can_submit_and_cancel_pending(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_procurement_user: User,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, admin)
    po = (await create_po(client, admin, test_project.id, vendor_id=vendor["id"])).json()
    proc = await auth_header(client, "procurement@test.com")
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"

    submitted = (await client.post(f"{url}/submit", headers={"Authorization": proc})).json()
    assert submitted["status"] == "pending_approval"
    cancelled = (await client.post(f"{url}/cancel", headers={"Authorization": proc})).json()
    assert cancelled["status"] == "cancelled"


@pytest.mark.asyncio
async def test_procurement_cannot_cancel_approved(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_procurement_user: User,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, admin)
    po = (await create_po(client, admin, test_project.id, vendor_id=vendor["id"])).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"
    await client.post(f"{url}/submit", headers={"Authorization": admin})
    await client.post(f"{url}/approve", headers={"Authorization": admin})

    proc = await auth_header(client, "procurement@test.com")
    assert (await client.post(f"{url}/cancel", headers={"Authorization": proc})).status_code == 403

    # Admin can cancel the APPROVED PO.
    assert (await client.post(f"{url}/cancel", headers={"Authorization": admin})).status_code == 200


@pytest.mark.asyncio
async def test_supervisor_client_403_everywhere(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_supervisor_user: User,
    test_client_user: User,
    test_project: Project,
):
    admin = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, admin)
    po = (await create_po(client, admin, test_project.id, vendor_id=vendor["id"])).json()
    base = f"/api/v1/projects/{test_project.id}/purchase-orders"

    sup = await auth_header(client, "supervisor@test.com")
    cli = await auth_header(client, "client@test.com")
    for header in (sup, cli):
        assert (await client.get(base, headers={"Authorization": header})).status_code == 403
        assert (await client.get(
            f"{base}/{po['id']}", headers={"Authorization": header}
        )).status_code == 403
        assert (await client.post(
            base, headers={"Authorization": header}, json=po_payload(vendor_id=vendor["id"])
        )).status_code == 403
        assert (await client.post(
            f"{base}/{po['id']}/submit", headers={"Authorization": header}
        )).status_code == 403


# --- Lifecycle gating -----------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_project_freezes_po(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)

    project = await test_db.get(Project, test_project.id)
    project.status = ProjectStatus.COMPLETED
    await test_db.commit()

    create = await create_po(client, header, test_project.id, vendor_id=vendor["id"])
    assert create.status_code == 400
    assert "frozen" in create.json()["detail"]


@pytest.mark.asyncio
async def test_archived_project_read_only(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()

    await client.post(f"/api/v1/projects/{test_project.id}/archive", headers={"Authorization": header})

    base = f"/api/v1/projects/{test_project.id}/purchase-orders"
    assert (await client.get(base, headers={"Authorization": header})).status_code == 200
    assert (await client.get(f"{base}/{po['id']}", headers={"Authorization": header})).status_code == 200
    assert (await client.post(
        f"{base}/{po['id']}/submit", headers={"Authorization": header}
    )).status_code == 403
    assert (await client.post(
        base, headers={"Authorization": header}, json=po_payload(vendor_id=vendor["id"])
    )).status_code == 403
    assert (await client.patch(
        f"{base}/{po['id']}", headers={"Authorization": header}, json={"notes": "x"}
    )).status_code == 403
    assert (await client.post(
        f"{base}/{po['id']}/lines", headers={"Authorization": header}, json=line_payload()
    )).status_code == 403


# --- IDOR -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_project_po_and_line_404(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    line = po["lines"][0]

    other = Project(
        project_code="PRJ-2026-0099",
        name="Intruder Residence",
        site_address="1 Intruder St",
        client_name="Intruder Co",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        budget_total=100000,
    )
    test_db.add(other)
    await test_db.commit()
    await test_db.refresh(other)

    base = f"/api/v1/projects/{other.id}/purchase-orders"
    assert (await client.get(
        f"{base}/{po['id']}", headers={"Authorization": header}
    )).status_code == 404
    assert (await client.patch(
        f"{base}/{po['id']}", headers={"Authorization": header}, json={"notes": "x"}
    )).status_code == 404
    assert (await client.post(
        f"{base}/{po['id']}/lines", headers={"Authorization": header}, json=line_payload()
    )).status_code == 404
    assert (await client.patch(
        f"{base}/{po['id']}/lines/{line['id']}",
        headers={"Authorization": header}, json={"quantity": 5},
    )).status_code == 404
    assert (await client.delete(
        f"{base}/{po['id']}/lines/{line['id']}",
        headers={"Authorization": header},
    )).status_code == 404


# --- Idempotency ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_po_create_replay(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    url = f"/api/v1/projects/{test_project.id}/purchase-orders"
    body = po_payload(vendor_id=vendor["id"])
    key = "key-po-create-0001"

    first = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key}, json=body)
    assert first.status_code == 201
    replay = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key}, json=body)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    listed = (await client.get(url, headers={"Authorization": header})).json()
    assert len(listed) == 1

    # Different body -> 409.
    conflict_body = dict(body)
    conflict_body["notes"] = "different"
    conflict = await client.post(
        url, headers={"Authorization": header, "Idempotency-Key": key}, json=conflict_body
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_idempotent_line_add_replay(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"], lines=[])).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines"
    body = line_payload()
    key = "key-po-line-0001"

    first = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key}, json=body)
    assert first.status_code == 201
    replay = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key}, json=body)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    after = await get_po(client, header, test_project.id, po["id"])
    assert len(after["lines"]) == 1
    assert after["total_amount"] == first.json()["line_total"]


@pytest.mark.asyncio
async def test_idempotent_line_add_different_body_409(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    """Reusing the line-add key for a different line body is a 409 (fingerprint
    mismatch), never a wrong replay."""
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"], lines=[])).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines"
    key = "key-po-line-0002"

    first = await client.post(
        url, headers={"Authorization": header, "Idempotency-Key": key}, json=line_payload()
    )
    assert first.status_code == 201
    conflict = await client.post(
        url,
        headers={"Authorization": header, "Idempotency-Key": key},
        json=line_payload(quantity=999),
    )
    assert conflict.status_code == 409

    after = await get_po(client, header, test_project.id, po["id"])
    assert len(after["lines"]) == 1


# --- Audit ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_events_recorded(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"

    # Nested lines are part of the create audit; separately-added lines get the
    # po_line_* actions.
    assert await audit_actions_for(test_db, "purchase_order_create", po["id"])
    added = (await add_line(client, header, test_project.id, po["id"])).json()
    assert await audit_actions_for(test_db, "po_line_add", added["id"])

    await client.patch(
        f"{url}/lines/{added['id']}", headers={"Authorization": header}, json={"quantity": 200}
    )
    assert await audit_actions_for(test_db, "po_line_update", added["id"])
    await client.delete(
        f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines/{added['id']}",
        headers={"Authorization": header},
    )
    assert await audit_actions_for(test_db, "po_line_remove", added["id"])

    await client.post(f"{url}/submit", headers={"Authorization": header})
    await client.post(f"{url}/approve", headers={"Authorization": header})
    for action in ("po_submit", "po_approve"):
        assert await audit_actions_for(test_db, action, po["id"])


@pytest.mark.asyncio
async def test_audit_records_rejection_and_cancel(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    vendor = await make_vendor(client, header)

    # reject -> revise -> submit -> cancel.
    po = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}"
    await client.post(f"{url}/submit", headers={"Authorization": header})
    await client.post(
        f"{url}/reject", headers={"Authorization": header}, json={"rejected_reason": "too expensive"}
    )
    await client.post(f"{url}/revise", headers={"Authorization": header})
    await client.post(f"{url}/submit", headers={"Authorization": header})
    await client.post(f"{url}/cancel", headers={"Authorization": header})
    for action in ("po_reject", "po_revise", "po_cancel"):
        assert await audit_actions_for(test_db, action, po["id"])

    # resubmit directly from REJECTED.
    po2 = (await create_po(client, header, test_project.id, vendor_id=vendor["id"])).json()
    url2 = f"/api/v1/projects/{test_project.id}/purchase-orders/{po2['id']}"
    await client.post(f"{url2}/submit", headers={"Authorization": header})
    await client.post(
        f"{url2}/reject", headers={"Authorization": header}, json={"rejected_reason": "try again"}
    )
    await client.post(f"{url2}/resubmit", headers={"Authorization": header})
    assert await audit_actions_for(test_db, "po_resubmit", po2["id"])


# --- Concurrency (real separate DB sessions) -------------------------------------


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
async def test_concurrent_po_creates_distinct_numbers(
    concurrent_client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_admin_user: User,
    test_project: Project,
):
    """Two concurrent creates serialize on the project row lock -> two POs with
    distinct po_numbers (no lost-update race on the sequence)."""
    header = await auth_header(concurrent_client, "admin@test.com")
    vendor = await make_vendor(concurrent_client, header)
    url = f"/api/v1/projects/{test_project.id}/purchase-orders"

    async def send() -> httpx.Response:
        return await concurrent_client.post(
            url, headers={"Authorization": header}, json=po_payload(vendor_id=vendor["id"])
        )

    responses = await asyncio.gather(send(), send())
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    numbers = sorted(r.json()["po_number"] for r in responses)
    assert numbers == ["PO-PRJ-TEST-0001-0001", "PO-PRJ-TEST-0001-0002"]


@pytest.mark.asyncio
async def test_concurrent_same_key_create_exactly_one_po(
    concurrent_client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_admin_user: User,
    test_project: Project,
):
    """Two concurrent same-key creates: the (actor, operation, key) unique index
    admits exactly one business op; the loser replays the winner. One PO, one
    idempotency record."""
    header = await auth_header(concurrent_client, "admin@test.com")
    vendor = await make_vendor(concurrent_client, header)
    url = f"/api/v1/projects/{test_project.id}/purchase-orders"
    body = po_payload(vendor_id=vendor["id"])
    key = "key-po-race-0001"

    async def send() -> httpx.Response:
        return await concurrent_client.post(
            url, headers={"Authorization": header, "Idempotency-Key": key}, json=body
        )

    responses = await asyncio.gather(send(), send())
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"]

    listed = (await concurrent_client.get(url, headers={"Authorization": header})).json()
    assert len(listed) == 1

    count = (
        await test_db.execute(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(IdempotencyRecord.idempotency_key == key)
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_line_adds_total_never_drifts(
    concurrent_client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_admin_user: User,
    test_project: Project,
):
    """Two concurrent line adds to the same DRAFT PO serialize on the project+
    PO locks; the final total equals the sum of all lines (never a lost update)."""
    header = await auth_header(concurrent_client, "admin@test.com")
    vendor = await make_vendor(concurrent_client, header)
    po = (
        await create_po(
            concurrent_client, header, test_project.id, vendor_id=vendor["id"],
            lines=[line_payload(quantity=1, unit_price=100)],
        )
    ).json()
    url = f"/api/v1/projects/{test_project.id}/purchase-orders/{po['id']}/lines"

    async def add(qty: float, price: float) -> httpx.Response:
        return await concurrent_client.post(
            url, headers={"Authorization": header},
            json=line_payload(quantity=qty, unit_price=price, description=f"line-{qty}-{price}"),
        )

    responses = await asyncio.gather(add(2, 50), add(3, 100))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]

    after = await get_po(concurrent_client, header, test_project.id, po["id"])
    line_sum = sum(line["line_total"] for line in after["lines"])
    assert after["total_amount"] == line_sum
    assert after["subtotal"] == line_sum
    # 100 (original) + 100 + 300.
    assert after["total_amount"] == 500.0
