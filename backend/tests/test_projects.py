"""
Tests for project endpoints and project-assignment RBAC (Phase 3, M2).

There was previously no test_projects.py at all — project CRUD had no
coverage. This file initially covers the assignment-management API added in
M2; project CRUD/PATCH/health tests land with the health milestone.
"""
import uuid

import httpx
import pytest

from app.models.project import Project
from app.models.user import User
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_admin_can_assign_and_list(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project, test_client_user: User
):
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/assignments",
        headers={"Authorization": header},
        json={"user_id": str(test_client_user.id)},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == str(test_client_user.id)

    listing = await client.get(
        f"/api/v1/projects/{test_project.id}/assignments", headers={"Authorization": header}
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert listing.json()[0]["email"] == "client@test.com"


@pytest.mark.asyncio
async def test_non_admin_cannot_manage_assignments(
    client: httpx.AsyncClient, test_procurement_user: User, test_project: Project, test_client_user: User
):
    header = await auth_header(client, "procurement@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/assignments",
        headers={"Authorization": header},
        json={"user_id": str(test_client_user.id)},
    )
    assert resp.status_code == 403

    listing = await client.get(
        f"/api/v1/projects/{test_project.id}/assignments", headers={"Authorization": header}
    )
    assert listing.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_assignment_rejected(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project, test_client_user: User
):
    header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}/assignments"
    first = await client.post(url, headers={"Authorization": header}, json={"user_id": str(test_client_user.id)})
    assert first.status_code == 201

    second = await client.post(url, headers={"Authorization": header}, json={"user_id": str(test_client_user.id)})
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_assign_nonexistent_user_404(client: httpx.AsyncClient, test_admin_user: User, test_project: Project):
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/assignments",
        headers={"Authorization": header},
        json={"user_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_assign_non_per_project_role_rejected(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project, test_procurement_user: User
):
    """Admin/procurement see all projects by role — assignment rows are only
    meaningful for supervisors and clients, so reject them."""
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/assignments",
        headers={"Authorization": header},
        json={"user_id": str(test_procurement_user.id)},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_unassign_revokes_client_access_immediately(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project, test_client_user: User
):
    admin_header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}/assignments"
    await client.post(url, headers={"Authorization": admin_header}, json={"user_id": str(test_client_user.id)})

    client_header = await auth_header(client, "client@test.com")
    before = await client.get(f"/api/v1/projects/{test_project.id}", headers={"Authorization": client_header})
    assert before.status_code == 200

    unassign = await client.delete(f"{url}/{test_client_user.id}", headers={"Authorization": admin_header})
    assert unassign.status_code == 204

    # Access is revoked within one request — no token/session invalidation needed.
    after = await client.get(f"/api/v1/projects/{test_project.id}", headers={"Authorization": client_header})
    assert after.status_code == 403


@pytest.mark.asyncio
async def test_unassign_to_supervisor_blocks_writes(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project, test_supervisor_user: User
):
    """Phase 2 RBAC enforcement relies on assignment for supervisors on
    write paths (tasks/logs). After unassignment, a supervisor gets 403."""
    admin_header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}/assignments"
    await client.post(url, headers={"Authorization": admin_header}, json={"user_id": str(test_supervisor_user.id)})

    unassign = await client.delete(f"{url}/{test_supervisor_user.id}", headers={"Authorization": admin_header})
    assert unassign.status_code == 204

    supervisor_header = await auth_header(client, "supervisor@test.com")

    task_resp = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": supervisor_header},
        json={"name": "Excavation", "start_date": "2026-02-01", "end_date": "2026-02-10"},
    )
    assert task_resp.status_code == 403


@pytest.mark.asyncio
async def test_unassign_nonexistent_404(client: httpx.AsyncClient, test_admin_user: User, test_project: Project):
    header = await auth_header(client, "admin@test.com")
    resp = await client.delete(
        f"/api/v1/projects/{test_project.id}/assignments/{uuid.uuid4()}",
        headers={"Authorization": header},
    )
    assert resp.status_code == 404