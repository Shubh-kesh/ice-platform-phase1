"""
Tests for Project Lifecycle & Admin (Phase 3, M10).

Covers: project creation with auto-generated unique codes, DRAFT → ACTIVE →
COMPLETED → ARCHIVED → RESTORE transitions (valid + invalid), lifecycle
transition RBAC (admin-only), archive visibility/filtering (hidden from
default lists, present in reporting / ?include_archived, 404 to non-admins),
audit rows with actor+timestamp, historical child-data retention across
COMPLETE/ARCHIVE, and the M4 invariant budget_spent == SUM(job_costs)
surviving lifecycle transitions.
"""
from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.project import Project, ProjectStatus
from app.models.user import User
from tests.conftest import auth_header

DRAFT = "draft"
ACTIVE = "active"
COMPLETED = "completed"
ARCHIVED = "archived"
PLANNING = "planning"


def project_payload(**overrides):
    payload = {
        "name": "New Residence, Pune",
        "site_address": "Baner, Pune, Maharashtra",
        "client_name": "Mr. Test Buyer",
        "start_date": "2026-09-01",
        "target_end_date": "2027-06-30",
        "budget_total": 4000000,
    }
    payload.update(overrides)
    return payload


def cost_payload(**overrides):
    payload = {
        "cost_code": "masonry",
        "description": "Cement blockwork",
        "amount": 250000,
        "incurred_on": "2026-08-01",
    }
    payload.update(overrides)
    return payload


# --- Creation + project code generation ---


@pytest.mark.asyncio
async def test_admin_creates_draft_project_with_unique_code(
    client: httpx.AsyncClient, test_admin_user: User
):
    header = await auth_header(client, "admin@test.com")
    r1 = await client.post(
        "/api/v1/projects", headers={"Authorization": header}, json=project_payload(name="A")
    )
    assert r1.status_code == 201
    body1 = r1.json()
    assert body1["status"] == DRAFT
    assert body1["project_code"] == f"PRJ-{date.today().year}-0001"
    assert body1["created_by"] == str(test_admin_user.id)

    r2 = await client.post(
        "/api/v1/projects", headers={"Authorization": header}, json=project_payload(name="B")
    )
    assert r2.status_code == 201
    body2 = r2.json()
    assert body2["project_code"] == f"PRJ-{date.today().year}-0002"
    assert body2["project_code"] != body1["project_code"]


@pytest.mark.asyncio
async def test_non_admin_cannot_create_project(
    client: httpx.AsyncClient, test_supervisor_user: User
):
    header = await auth_header(client, "supervisor@test.com")
    resp = await client.post(
        "/api/v1/projects", headers={"Authorization": header}, json=project_payload()
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_patch_status_and_budget_spent_rejected(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    """status moves only via dedicated lifecycle endpoints; budget_spent is
    derived (M4) and must not be hand-writable."""
    header = await auth_header(client, "admin@test.com")
    resp = await client.patch(
        f"/api/v1/projects/{test_project.id}",
        headers={"Authorization": header},
        json={"status": COMPLETED, "budget_spent": 999999},
    )
    # Unknown fields are ignored by the schema (not set as lifecycle), and the
    # project must NOT change status or hand-spend.
    assert resp.status_code == 200
    assert resp.json()["status"] != COMPLETED

    get = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert get.json()["budget_spent"] == 0.0  # unchanged from test_project default


# --- Lifecycle transitions ---


@pytest.mark.asyncio
async def test_full_lifecycle_chain(client: httpx.AsyncClient, test_admin_user: User):
    header = await auth_header(client, "admin@test.com")
    created = await client.post(
        "/api/v1/projects", headers={"Authorization": header}, json=project_payload()
    )
    pid = created.json()["id"]
    events = []

    for path, expected in [
        ("activate", ACTIVE),
        ("complete", COMPLETED),
        ("archive", ARCHIVED),
    ]:
        resp = await client.post(f"/api/v1/projects/{pid}/{path}", headers={"Authorization": header})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == expected
        events.append(resp.json())

    completed = events[1]
    assert completed["completed_by"] == str(test_admin_user.id)
    assert completed["completed_at"] is not None
    assert completed["percent_complete"] == 100
    archived = events[2]
    assert archived["archived_by"] == str(test_admin_user.id)
    assert archived["archived_at"] is not None

    # Restore returns completed (it was completed before archiving).
    restored = await client.post(f"/api/v1/projects/{pid}/restore", headers={"Authorization": header})
    assert restored.status_code == 200
    rbody = restored.json()
    assert rbody["status"] == COMPLETED
    assert rbody["restored_by"] == str(test_admin_user.id)
    assert rbody["archived_at"] is None


@pytest.mark.asyncio
async def test_restore_draft_to_active(client: httpx.AsyncClient, test_admin_user: User):
    """A project archived straight from ACTIVE returns to ACTIVE on restore."""
    header = await auth_header(client, "admin@test.com")
    created = await client.post(
        "/api/v1/projects", headers={"Authorization": header}, json=project_payload()
    )
    pid = created.json()["id"]
    await client.post(f"/api/v1/projects/{pid}/activate", headers={"Authorization": header})
    await client.post(f"/api/v1/projects/{pid}/archive", headers={"Authorization": header})

    restored = await client.post(f"/api/v1/projects/{pid}/restore", headers={"Authorization": header})
    assert restored.status_code == 200
    assert restored.json()["status"] == ACTIVE


@pytest.mark.asyncio
async def test_invalid_transitions_rejected(client: httpx.AsyncClient, test_admin_user: User):
    header = await auth_header(client, "admin@test.com")
    created = await client.post(
        "/api/v1/projects", headers={"Authorization": header}, json=project_payload()
    )
    pid = created.json()["id"]

    # DRAFT cannot be completed or archived directly.
    assert (
        await client.post(f"/api/v1/projects/{pid}/complete", headers={"Authorization": header})
    ).status_code == 400
    assert (
        await client.post(f"/api/v1/projects/{pid}/archive", headers={"Authorization": header})
    ).status_code == 400

    await client.post(f"/api/v1/projects/{pid}/activate", headers={"Authorization": header})
    # ACTIVE cannot be activated again.
    assert (
        await client.post(f"/api/v1/projects/{pid}/activate", headers={"Authorization": header})
    ).status_code == 400
    # ACTIVE cannot be restored.
    assert (
        await client.post(f"/api/v1/projects/{pid}/restore", headers={"Authorization": header})
    ).status_code == 400


@pytest.mark.asyncio
async def test_lifecycle_transitions_admin_only(
    client: httpx.AsyncClient,
    test_project: Project,
    test_supervisor_user: User,
    test_procurement_user: User,
    test_client_user: User,
):
    for email in ("supervisor@test.com", "procurement@test.com", "client@test.com"):
        header = await auth_header(client, email)
        for path in ("activate", "complete", "archive", "restore"):
            resp = await client.post(
                f"/api/v1/projects/{test_project.id}/{path}", headers={"Authorization": header}
            )
            assert resp.status_code == 403, (email, path, resp.status_code)


# --- Archive visibility / filtering ---


@pytest.mark.asyncio
async def test_archived_hidden_from_default_list(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    await client.post(f"/api/v1/projects/{test_project.id}/archive", headers={"Authorization": header})

    listing = await client.get("/api/v1/projects", headers={"Authorization": header})
    assert listing.status_code == 200
    assert all(p["id"] != str(test_project.id) for p in listing.json())

    including_archived = await client.get(
        "/api/v1/projects?include_archived=true", headers={"Authorization": header}
    )
    assert including_archived.status_code == 200
    assert any(p["id"] == str(test_project.id) for p in including_archived.json())


@pytest.mark.asyncio
async def test_archived_inaccessible_to_non_admins(
    client: httpx.AsyncClient, test_db, test_admin_user: User, test_project: Project, test_supervisor_user: User
):
    """A supervisor who IS assigned gets 404 (not 403) on an archived project —
    the archived state hides the project, and its existence must not leak."""
    from tests.conftest import assign_user_to_project

    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)

    admin_header = await auth_header(client, "admin@test.com")
    await client.post(f"/api/v1/projects/{test_project.id}/archive", headers={"Authorization": admin_header})

    # Sanity: assignment works for a non-archived twin.
    twin = Project(
        project_code="PRJ-TEST-0002",
        name="Twin",
        site_address="addr",
        client_name="client",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        budget_total=1000,
    )
    test_db.add(twin)
    await test_db.commit()
    await assign_user_to_project(test_db, twin.id, test_supervisor_user.id)

    supervisor_header = await auth_header(client, "supervisor@test.com")
    visible = await client.get(
        f"/api/v1/projects/{twin.id}", headers={"Authorization": supervisor_header}
    )
    assert visible.status_code == 200

    # 404, not 403 — archived project existence must not leak to non-admins.
    resp = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": supervisor_header}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_completed_visible_in_lists(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    """COMPLETED projects remain in normal reporting lists (only ARCHIVED are hidden)."""
    header = await auth_header(client, "admin@test.com")
    await client.post(f"/api/v1/projects/{test_project.id}/activate", headers={"Authorization": header})
    resp = await client.post(f"/api/v1/projects/{test_project.id}/complete", headers={"Authorization": header})
    assert resp.status_code == 200
    assert resp.json()["status"] == COMPLETED

    listing = await client.get("/api/v1/projects", headers={"Authorization": header})
    assert any(p["id"] == str(test_project.id) for p in listing.json())


# --- Audit trail ---


@pytest.mark.asyncio
async def test_lifecycle_transitions_audited(
    client: httpx.AsyncClient, test_db, test_admin_user: User
):
    header = await auth_header(client, "admin@test.com")
    created = await client.post(
        "/api/v1/projects", headers={"Authorization": header}, json=project_payload()
    )
    pid = created.json()["id"]
    for path in ("activate", "complete", "archive"):
        await client.post(f"/api/v1/projects/{pid}/{path}", headers={"Authorization": header})

    audits = (
        await test_db.execute(
            select(AuditLog).where(AuditLog.table_name == "projects", AuditLog.record_id == pid)
        )
    ).scalars().all()
    actions = [a.action for a in audits]
    assert "create" in actions
    assert actions.count("activate") == 1
    assert actions.count("complete") == 1
    assert actions.count("archive") == 1

    actor_ids = {a.user_id for a in audits}
    assert {test_admin_user.id} == actor_ids
    for a in audits:
        if a.action in ("activate", "complete", "archive"):
            assert "status" in a.changes
            assert a.changes["status"]["old"] in (DRAFT, ACTIVE, COMPLETED)
            assert a.changes["status"]["new"] in (ACTIVE, COMPLETED, ARCHIVED)


# --- Historical data retention + M4 invariant across lifecycle ---


@pytest.mark.asyncio
async def test_child_data_and_budget_invariant_survive_complete_and_archive(
    client: httpx.AsyncClient, test_db, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")

    # Record a job cost (M4 ledger-derived budget).
    cost = await client.post(
        f"/api/v1/projects/{test_project.id}/job-costs",
        headers={"Authorization": header},
        json=cost_payload(),
    )
    assert cost.status_code == 201

    get = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert get.json()["budget_spent"] == 250000.0

    # Walk lifecycle to ARCHIVED (must activate first since fixture is ACTIVE
    # → completes from ACTIVE).
    await client.post(f"/api/v1/projects/{test_project.id}/complete", headers={"Authorization": header})
    await client.post(f"/api/v1/projects/{test_project.id}/archive", headers={"Authorization": header})

    # M4 invariant: budget_spent == SUM(job_costs) still holds after archive.
    from app.services.finance import sum_job_costs

    ledger = await sum_job_costs(test_db, test_project.id)
    assert ledger == 250000
    final = (
        await test_db.execute(select(Project).where(Project.id == test_project.id))
    ).scalar_one()
    assert float(final.budget_spent) == 250000.0
    assert final.status == ProjectStatus.ARCHIVED

    # Job costs still queryable via admin reporting read (not hard-deleted).
    costs = await client.get(
        f"/api/v1/projects/{test_project.id}/job-costs", headers={"Authorization": header}
    )
    assert costs.status_code == 200
    assert len(costs.json()) == 1