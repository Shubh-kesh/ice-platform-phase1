"""
Tests for daily site log endpoints and their RBAC rules.
"""
import httpx
import pytest

from app.models.project import Project
from app.models.user import User
from tests.conftest import assign_user_to_project, auth_header


@pytest.mark.asyncio
async def test_assigned_supervisor_can_create_log(
    client: httpx.AsyncClient, test_db, test_supervisor_user: User, test_project: Project
):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    header = await auth_header(client, "supervisor@test.com")

    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/site-logs",
        headers={"Authorization": header},
        json={
            "log_date": "2026-08-09",
            "work_summary": "Poured foundation slab, 12 workers on site.",
            "workers_present": 12,
            "weather": "Clear",
        },
    )
    assert resp.status_code == 201
    log = resp.json()
    assert log["work_summary"].startswith("Poured foundation")
    assert log["photo_urls"] == []


@pytest.mark.asyncio
async def test_unassigned_supervisor_cannot_create_log(
    client: httpx.AsyncClient, test_supervisor_user: User, test_project: Project
):
    header = await auth_header(client, "supervisor@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/site-logs",
        headers={"Authorization": header},
        json={"log_date": "2026-08-09", "work_summary": "Work done."},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_create_log_but_can_read(
    client: httpx.AsyncClient, test_db, test_admin_user: User, test_client_user: User, test_project: Project
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    admin_header = await auth_header(client, "admin@test.com")
    write_resp = await client.post(
        f"/api/v1/projects/{test_project.id}/site-logs",
        headers={"Authorization": admin_header},
        json={"log_date": "2026-08-09", "work_summary": "Admin-entered log."},
    )
    assert write_resp.status_code == 201

    client_header = await auth_header(client, "client@test.com")
    read_resp = await client.get(
        f"/api/v1/projects/{test_project.id}/site-logs", headers={"Authorization": client_header}
    )
    assert read_resp.status_code == 200
    assert len(read_resp.json()) == 1

    client_write_resp = await client.post(
        f"/api/v1/projects/{test_project.id}/site-logs",
        headers={"Authorization": client_header},
        json={"log_date": "2026-08-09", "work_summary": "Should not be allowed."},
    )
    assert client_write_resp.status_code == 403


@pytest.mark.asyncio
async def test_empty_work_summary_rejected(
    client: httpx.AsyncClient, test_db, test_supervisor_user: User, test_project: Project
):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    header = await auth_header(client, "supervisor@test.com")

    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/site-logs",
        headers={"Authorization": header},
        json={"log_date": "2026-08-09", "work_summary": ""},
    )
    assert resp.status_code == 422
