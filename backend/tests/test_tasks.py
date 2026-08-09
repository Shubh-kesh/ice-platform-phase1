"""
Tests for Gantt/timeline task endpoints and their RBAC rules.
"""
import httpx
import pytest

from app.models.project import Project
from app.models.user import User
from tests.conftest import assign_user_to_project, auth_header


@pytest.mark.asyncio
async def test_admin_can_create_and_list_tasks(client: httpx.AsyncClient, test_admin_user: User, test_project: Project):
    header = await auth_header(client, "admin@test.com")

    create_resp = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": header},
        json={"name": "Foundation", "start_date": "2026-01-01", "end_date": "2026-02-01"},
    )
    assert create_resp.status_code == 201
    task = create_resp.json()
    assert task["name"] == "Foundation"
    assert task["status"] == "not_started"

    list_resp = await client.get(f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header})
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_invalid_date_range_rejected(client: httpx.AsyncClient, test_admin_user: User, test_project: Project):
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": header},
        json={"name": "Bad Task", "start_date": "2026-02-01", "end_date": "2026-01-01"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unassigned_supervisor_cannot_write_tasks(
    client: httpx.AsyncClient, test_supervisor_user: User, test_project: Project
):
    header = await auth_header(client, "supervisor@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": header},
        json={"name": "Framing", "start_date": "2026-01-01", "end_date": "2026-02-01"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_assigned_supervisor_can_write_tasks(
    client: httpx.AsyncClient, test_db, test_supervisor_user: User, test_project: Project
):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    header = await auth_header(client, "supervisor@test.com")

    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": header},
        json={"name": "Framing", "start_date": "2026-01-01", "end_date": "2026-02-01"},
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_client_cannot_write_but_can_read_if_assigned(
    client: httpx.AsyncClient, test_db, test_admin_user: User, test_client_user: User, test_project: Project
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    admin_header = await auth_header(client, "admin@test.com")
    await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": admin_header},
        json={"name": "Roofing", "start_date": "2026-03-01", "end_date": "2026-04-01"},
    )

    client_header = await auth_header(client, "client@test.com")
    read_resp = await client.get(
        f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": client_header}
    )
    assert read_resp.status_code == 200
    assert len(read_resp.json()) == 1

    write_resp = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": client_header},
        json={"name": "Painting", "start_date": "2026-04-01", "end_date": "2026-05-01"},
    )
    assert write_resp.status_code == 403


@pytest.mark.asyncio
async def test_task_dependency_must_be_in_same_project(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": header},
        json={
            "name": "Electrical",
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
            "depends_on_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_and_delete_task(client: httpx.AsyncClient, test_admin_user: User, test_project: Project):
    header = await auth_header(client, "admin@test.com")
    created = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/tasks",
            headers={"Authorization": header},
            json={"name": "Plumbing", "start_date": "2026-01-01", "end_date": "2026-02-01"},
        )
    ).json()

    update_resp = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{created['id']}",
        headers={"Authorization": header},
        json={"percent_complete": 50, "status": "in_progress"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["percent_complete"] == 50

    delete_resp = await client.delete(
        f"/api/v1/projects/{test_project.id}/tasks/{created['id']}",
        headers={"Authorization": header},
    )
    assert delete_resp.status_code == 204

    list_resp = await client.get(f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header})
    assert list_resp.json() == []
