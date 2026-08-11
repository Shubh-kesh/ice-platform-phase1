"""
M5 — billing milestones + milestone-driven invoice tests.

Covers the invoicing domain over the real ASGI client:
  * Milestone CRUD — one-rule invariant, duplicate-name 409, freeze rules.
  * Completion — terminal, audited, frozen on COMPLETED projects.
  * Invoice generation — eligibility gate (COMPLETED milestone only), server-
    side amount derivation, invoice-number sequencing, double-bill guards
    (app-level 409 + DB partial unique index under concurrency), idempotency.
  * Status transitions — DRAFT -> SENT -> PAID, DRAFT|SENT -> CANCELLED, with
    state guards and re-issue after cancellation.
  * RBAC — admin owns everything, procurement is view-only, supervisors see
    nothing, clients see only their assigned projects' restricted shape.
  * Auditing — every mutation records an audit row with the acting user.
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
from app.models.project import Project, ProjectStatus
from app.models.user import User
from tests.conftest import TEST_DATABASE_URL, assign_user_to_project, auth_header


def milestone_payload(**overrides):
    payload = {
        "name": "Foundation",
        "billing_type": "percentage",
        "billing_percentage": 20,
        "sort_order": 1,
        "description": "Ground floor + slab",
    }
    payload.update(overrides)
    return payload


async def create_milestone(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, **overrides
):
    return await client.post(
        f"/api/v1/projects/{project_id}/billing-milestones",
        headers={"Authorization": header},
        json=milestone_payload(**overrides),
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


async def run_milestone_to_invoice(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, **overrides
):
    """Helper — create + complete a milestone and generate its invoice. Returns
    (milestone, invoice) dicts."""
    m = (await create_milestone(client, header, project_id, **overrides)).json()
    await complete_milestone(client, header, project_id, m["id"])
    inv = (await make_invoice(client, header, project_id, m["id"])).json()
    return m, inv


async def audit_actions_for(
    db: AsyncSession, action: str, record_id: str | None = None
) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.action == action)
    if record_id is not None:
        stmt = stmt.where(AuditLog.record_id == record_id)
    return list((await db.execute(stmt)).scalars().all())


# --- Milestone configuration -------------------------------------------------


@pytest.mark.asyncio
async def test_create_percentage_milestone(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    resp = await create_milestone(client, header, test_project.id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Foundation"
    assert body["billing_type"] == "percentage"
    assert body["billing_percentage"] == 20.0
    assert body["fixed_amount"] is None
    assert body["status"] == "not_started"
    assert body["project_id"] == str(test_project.id)


@pytest.mark.asyncio
async def test_create_fixed_amount_milestone(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    resp = await create_milestone(
        client, header, test_project.id, name="Interior fit-out",
        billing_type="fixed_amount", billing_percentage=None, fixed_amount=333333.33,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["billing_type"] == "fixed_amount"
    assert body["fixed_amount"] == 333333.33
    assert body["billing_percentage"] is None


@pytest.mark.asyncio
async def test_milestone_requires_exactly_one_rule(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    both = await create_milestone(
        client, header, test_project.id, name="Both", billing_type="fixed_amount",
        fixed_amount=1000, billing_percentage=20,
    )
    assert both.status_code == 422

    none_rule = await create_milestone(
        client, header, test_project.id, name="None", billing_type="percentage",
        billing_percentage=None,
    )
    assert none_rule.status_code == 422

    bad_pct = await create_milestone(
        client, header, test_project.id, name="BadPct", billing_type="percentage",
        billing_percentage=150,
    )
    assert bad_pct.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_milestone_name_409(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    first = await create_milestone(client, header, test_project.id)
    assert first.status_code == 201
    dup = await create_milestone(client, header, test_project.id)
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_list_milestones_ordered_by_sort_order(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    await create_milestone(client, header, test_project.id, name="Z", sort_order=2)
    await create_milestone(client, header, test_project.id, name="A", sort_order=1)
    await create_milestone(client, header, test_project.id, name="M", sort_order=1)
    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/billing-milestones",
        headers={"Authorization": header},
    )
    assert resp.status_code == 200
    names = [m["name"] for m in resp.json()]
    assert names == ["A", "M", "Z"]  # sort_order asc, then created_at asc


@pytest.mark.asyncio
async def test_milestone_non_admin_write_forbidden(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_supervisor_user: User,
    test_procurement_user: User,
    test_client_user: User,
    test_project: Project,
):
    for email in ("supervisor@test.com", "procurement@test.com", "client@test.com"):
        header = await auth_header(client, email)
        resp = await create_milestone(client, header, test_project.id, name=email)
        assert resp.status_code == 403, email
    # Procurement may read the schedule-of-values.
    proc_header = await auth_header(client, "procurement@test.com")
    read = await client.get(
        f"/api/v1/projects/{test_project.id}/billing-milestones",
        headers={"Authorization": proc_header},
    )
    assert read.status_code == 200


@pytest.mark.asyncio
async def test_update_milestone_and_duplicate_rename(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, header, test_project.id)).json()
    other = (await create_milestone(client, header, test_project.id, name="Other")).json()
    assert other["id"] != m["id"]

    updated = await client.patch(
        f"/api/v1/projects/{test_project.id}/billing-milestones/{m['id']}",
        headers={"Authorization": header},
        json={"name": "Foundation v2", "description": "revised"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Foundation v2"
    assert len(await audit_actions_for(test_db, "billing_milestone_update", m["id"])) == 1

    collide = await client.patch(
        f"/api/v1/projects/{test_project.id}/billing-milestones/{m['id']}",
        headers={"Authorization": header},
        json={"name": "Other"},
    )
    assert collide.status_code == 409


@pytest.mark.asyncio
async def test_update_billing_type_clears_other_rule(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, header, test_project.id)).json()
    switched = await client.patch(
        f"/api/v1/projects/{test_project.id}/billing-milestones/{m['id']}",
        headers={"Authorization": header},
        json={"billing_type": "fixed_amount", "fixed_amount": 5000},
    )
    assert switched.status_code == 200
    body = switched.json()
    assert body["billing_type"] == "fixed_amount"
    assert body["fixed_amount"] == 5000.0
    assert body["billing_percentage"] is None


@pytest.mark.asyncio
async def test_update_does_not_accept_delete(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, header, test_project.id)).json()
    resp = await client.request(
        "DELETE", f"/api/v1/projects/{test_project.id}/billing-milestones/{m['id']}",
        headers={"Authorization": header},
    )
    assert resp.status_code == 405


# --- Completion --------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_milestone_is_terminal_and_audited(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, header, test_project.id)).json()
    done = await complete_milestone(client, header, test_project.id, m["id"])
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None
    assert body["completed_by"] == str(test_admin_user.id)

    again = await complete_milestone(client, header, test_project.id, m["id"])
    assert again.status_code == 400

    logs = await audit_actions_for(test_db, "billing_milestone_completed", m["id"])
    assert len(logs) == 1
    assert logs[0].user_id == test_admin_user.id


@pytest.mark.asyncio
async def test_milestone_invoice_reference_makes_it_immutable(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    """Completing a milestone does not freeze it, but once an invoice exists the
    milestone's rule can no longer change (the paper trail must not desync)."""
    header = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, header, test_project.id)).json()
    await complete_milestone(client, header, test_project.id, m["id"])
    edit_after_complete = await client.patch(
        f"/api/v1/projects/{test_project.id}/billing-milestones/{m['id']}",
        headers={"Authorization": header},
        json={"description": "still editable before invoicing"},
    )
    assert edit_after_complete.status_code == 200

    await make_invoice(client, header, test_project.id, m["id"])
    edit_after_invoice = await client.patch(
        f"/api/v1/projects/{test_project.id}/billing-milestones/{m['id']}",
        headers={"Authorization": header},
        json={"description": "should fail now"},
    )
    assert edit_after_invoice.status_code == 409


# --- Invoice generation ------------------------------------------------------


@pytest.mark.asyncio
async def test_invoice_generated_from_percentage_milestone(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m, inv = await run_milestone_to_invoice(client, header, test_project.id)
    assert inv["amount"] == 200000.0  # 20% of budget_total 1000000
    assert inv["status"] == "draft"
    assert inv["billing_milestone_id"] == m["id"]
    assert inv["invoice_number"] == "INV-PRJ-TEST-0001-0001"
    assert inv["overdue"] is False
    assert inv["due_date"] == (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
    assert len(await audit_actions_for(test_db, "invoice_create", inv["id"])) == 1


@pytest.mark.asyncio
async def test_invoice_generated_from_fixed_milestone(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m, inv = await run_milestone_to_invoice(
        client, header, test_project.id, name="Fit-out", billing_type="fixed_amount",
        billing_percentage=None, fixed_amount=333333.33,
    )
    assert inv["amount"] == 333333.33
    assert inv["milestone_name"] == "Fit-out"


@pytest.mark.asyncio
async def test_invoice_number_sequences_per_project(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    _, inv1 = await run_milestone_to_invoice(client, header, test_project.id, name="A")
    _, inv2 = await run_milestone_to_invoice(client, header, test_project.id, name="B")
    assert inv1["invoice_number"] == "INV-PRJ-TEST-0001-0001"
    assert inv2["invoice_number"] == "INV-PRJ-TEST-0001-0002"


@pytest.mark.asyncio
async def test_invoice_requires_completed_milestone(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, header, test_project.id)).json()
    resp = await make_invoice(client, header, test_project.id, m["id"])
    assert resp.status_code == 400
    assert "completed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_double_billing_same_milestone_409(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m, _ = await run_milestone_to_invoice(client, header, test_project.id)
    again = await make_invoice(client, header, test_project.id, m["id"])
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_cancelled_invoice_frees_milestone_for_reissue(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m, inv = await run_milestone_to_invoice(client, header, test_project.id)
    cancelled = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/cancel",
        headers={"Authorization": header},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    reissued = await make_invoice(client, header, test_project.id, m["id"])
    assert reissued.status_code == 201
    assert reissued.json()["invoice_number"] == "INV-PRJ-TEST-0001-0002"


@pytest.mark.asyncio
async def test_invoice_not_generated_on_non_active_projects(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, header, test_project.id)).json()
    await complete_milestone(client, header, test_project.id, m["id"])

    project = await test_db.get(Project, test_project.id)
    project.status = ProjectStatus.COMPLETED
    await test_db.commit()

    completed = await make_invoice(client, header, test_project.id, m["id"])
    assert completed.status_code == 400
    assert "ACTIVE" in completed.json()["detail"]

    project.status = ProjectStatus.ACTIVE
    await test_db.commit()
    archived = await client.post(
        f"/api/v1/projects/{test_project.id}/archive", headers={"Authorization": header}
    )
    assert archived.status_code == 200
    archived_inv = await make_invoice(client, header, test_project.id, m["id"])
    assert archived_inv.status_code == 403  # assert_project_writable


@pytest.mark.asyncio
async def test_invoice_amount_rounding_half_up(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    project = await test_db.get(Project, test_project.id)
    project.budget_total = 999999.99
    await test_db.commit()

    m, inv = await run_milestone_to_invoice(client, header, test_project.id)
    assert inv["amount"] == 200000.0  # 999999.99 * 0.2 = 199999.998 -> 200000.00


@pytest.mark.asyncio
async def test_invoice_creation_idempotent_replay(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, header, test_project.id)).json()
    await complete_milestone(client, header, test_project.id, m["id"])
    key = str(uuid.uuid4())
    url = f"/api/v1/projects/{test_project.id}/invoices"
    body = {"billing_milestone_id": str(m["id"])}

    first = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key}, json=body)
    retry = await client.post(url, headers={"Authorization": header, "Idempotency-Key": key}, json=body)
    assert first.status_code == 201 and retry.status_code == 201
    assert retry.json() == first.json()

    invoices = (await client.get(url, headers={"Authorization": header})).json()
    assert len(invoices) == 1


# --- Status transitions ------------------------------------------------------


async def _sent_invoice(client, header, project_id):
    m, inv = await run_milestone_to_invoice(client, header, project_id)
    issued = await client.post(
        f"/api/v1/projects/{project_id}/invoices/{inv['id']}/issue",
        headers={"Authorization": header},
    )
    return m, issued.json()


@pytest.mark.asyncio
async def test_issue_then_mark_paid_flow(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    _, sent = await _sent_invoice(client, header, test_project.id)
    assert sent["status"] == "sent"
    assert sent["issued_at"] is not None
    assert sent["issued_by"] == str(test_admin_user.id)

    paid = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{sent['id']}/mark-paid",
        headers={"Authorization": header},
    )
    assert paid.status_code == 200
    body = paid.json()
    assert body["status"] == "paid"
    assert body["paid_at"] is not None
    assert body["paid_by"] == str(test_admin_user.id)

    assert len(await audit_actions_for(test_db, "invoice_issue", sent["id"])) == 1
    assert len(await audit_actions_for(test_db, "invoice_paid", sent["id"])) == 1


@pytest.mark.asyncio
async def test_transition_state_guards(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m, inv = await run_milestone_to_invoice(client, header, test_project.id)

    paid_from_draft = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/mark-paid",
        headers={"Authorization": header},
    )
    assert paid_from_draft.status_code == 400

    issued = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/issue",
        headers={"Authorization": header},
    )
    assert issued.status_code == 200
    reissue = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/issue",
        headers={"Authorization": header},
    )
    assert reissue.status_code == 400

    paid = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/mark-paid",
        headers={"Authorization": header},
    )
    assert paid.status_code == 200
    cancel_paid = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/cancel",
        headers={"Authorization": header},
    )
    assert cancel_paid.status_code == 400


@pytest.mark.asyncio
async def test_cancel_from_draft_and_sent_is_terminal_and_audited(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    _, inv1 = await run_milestone_to_invoice(client, header, test_project.id, name="C1")
    cancel_draft = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv1['id']}/cancel",
        headers={"Authorization": header},
    )
    assert cancel_draft.status_code == 200
    assert cancel_draft.json()["status"] == "cancelled"
    assert len(await audit_actions_for(test_db, "invoice_cancelled", inv1["id"])) == 1

    _, inv2 = await run_milestone_to_invoice(client, header, test_project.id, name="C2")
    issued = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv2['id']}/issue",
        headers={"Authorization": header},
    )
    assert issued.status_code == 200
    cancel_sent = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv2['id']}/cancel",
        headers={"Authorization": header},
    )
    assert cancel_sent.status_code == 200
    assert cancel_sent.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_transitions_frozen_on_non_active_projects(
    client: httpx.AsyncClient, test_db: AsyncSession, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    _, inv = await run_milestone_to_invoice(client, header, test_project.id)

    project = await test_db.get(Project, test_project.id)
    project.status = ProjectStatus.COMPLETED
    await test_db.commit()

    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/issue",
        headers={"Authorization": header},
    )
    assert resp.status_code == 400
    assert "ACTIVE" in resp.json()["detail"]


# --- Overdue derivation ------------------------------------------------------


@pytest.mark.asyncio
async def test_overdue_derived_for_past_due_sent_invoice(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, header, test_project.id)).json()
    await complete_milestone(client, header, test_project.id, m["id"])
    inv = (await make_invoice(
        client, header, test_project.id, m["id"],
        due_date=(date.today() - timedelta(days=5)).isoformat(),
    )).json()
    draft = (await client.get(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}",
        headers={"Authorization": header},
    )).json()
    assert draft["overdue"] is False  # DRAFT is never overdue

    issued = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/issue",
        headers={"Authorization": header},
    )
    assert issued.status_code == 200
    sent = (await client.get(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}",
        headers={"Authorization": header},
    )).json()
    assert sent["overdue"] is True


# --- RBAC --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_procurement_is_view_only(
    client: httpx.AsyncClient, test_admin_user: User, test_procurement_user: User, test_project: Project
):
    admin_header = await auth_header(client, "admin@test.com")
    m, inv = await run_milestone_to_invoice(client, header=admin_header, project_id=test_project.id)
    proc_header = await auth_header(client, "procurement@test.com")

    read = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": proc_header}
    )
    assert read.status_code == 200
    assert len(read.json()) == 1

    create = await make_invoice(client, proc_header, test_project.id, m["id"])
    assert create.status_code == 403
    issue = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/issue",
        headers={"Authorization": proc_header},
    )
    assert issue.status_code == 403
    pay = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/mark-paid",
        headers={"Authorization": proc_header},
    )
    assert pay.status_code == 403
    cancel = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/cancel",
        headers={"Authorization": proc_header},
    )
    assert cancel.status_code == 403


@pytest.mark.asyncio
async def test_supervisor_has_no_finance_surface(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_supervisor_user: User,
    test_project: Project,
):
    header = await auth_header(client, "supervisor@test.com")
    invoices = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": header}
    )
    assert invoices.status_code == 403
    milestones = await client.get(
        f"/api/v1/projects/{test_project.id}/billing-milestones",
        headers={"Authorization": header},
    )
    assert milestones.status_code == 403


@pytest.mark.asyncio
async def test_client_sees_restricted_shape_only(
    client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_admin_user: User,
    test_client_user: User,
    test_project: Project,
):
    admin_header = await auth_header(client, "admin@test.com")
    m, inv = await run_milestone_to_invoice(client, header=admin_header, project_id=test_project.id)
    issued = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/issue",
        headers={"Authorization": admin_header},
    )
    assert issued.status_code == 200

    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    client_header = await auth_header(client, "client@test.com")

    listed = (await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": client_header}
    )).json()
    assert len(listed) == 1
    row = listed[0]
    assert row["id"] == inv["id"]
    assert row["milestone_name"] == "Foundation"
    assert row["amount"] == 200000.0
    assert row["status"] == "sent"
    for secret in ("notes", "issued_by", "paid_by", "cancelled_by", "billing_milestone_id"):
        assert secret not in row

    milestones = await client.get(
        f"/api/v1/projects/{test_project.id}/billing-milestones",
        headers={"Authorization": client_header},
    )
    assert milestones.status_code == 403  # schedule-of-values is internal


@pytest.mark.asyncio
async def test_client_unassigned_project_403(
    client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_admin_user: User,
    test_client_user: User,
    test_project: Project,
):
    header = await auth_header(client, "client@test.com")
    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": header}
    )
    assert resp.status_code == 403  # assert_can_view_project, no assignment


@pytest.mark.asyncio
async def test_client_reads_archived_project_as_404(
    client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_admin_user: User,
    test_client_user: User,
    test_project: Project,
):
    header = await auth_header(client, "admin@test.com")
    await client.post(
        f"/api/v1/projects/{test_project.id}/archive", headers={"Authorization": header}
    )
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    client_header = await auth_header(client, "client@test.com")
    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": client_header}
    )
    assert resp.status_code == 404


# --- Concurrency -------------------------------------------------------------


@pytest.fixture
async def concurrent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Per-request DB session so two no-key invoice creates race for real."""
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
async def test_concurrent_no_key_creates_exactly_one_invoice(
    concurrent_client: httpx.AsyncClient,
    test_admin_user: User,
    test_project: Project,
):
    """Two in-flight no-key creates for the same milestone: the partial unique
    index allows exactly one invoice; the loser gets a clean 409."""
    header = await auth_header(concurrent_client, "admin@test.com")
    m = (await create_milestone(concurrent_client, header, test_project.id)).json()
    await complete_milestone(concurrent_client, header, test_project.id, m["id"])
    url = f"/api/v1/projects/{test_project.id}/invoices"
    body = {"billing_milestone_id": str(m["id"])}

    async def send() -> httpx.Response:
        return await concurrent_client.post(url, headers={"Authorization": header}, json=body)

    responses = await asyncio.gather(send(), send())
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409], [r.text for r in responses]

    invoices = (await concurrent_client.get(url, headers={"Authorization": header})).json()
    assert len(invoices) == 1
    assert all(i["status"] == "draft" for i in invoices)
