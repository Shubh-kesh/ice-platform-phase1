"""
Tests for Gantt/timeline task endpoints and their RBAC rules.

M7 adds the write-path validation coverage: date-order on PATCH (full and
partial updates), dependency integrity (same-project, self, existence) on
PATCH, dependency-cycle rejection, and the concurrency guarantee that the
project row lock serializes task writes so a cycle can never be committed.
"""
import asyncio
import uuid
from datetime import date
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from app.models.project import Project, ProjectStatus
from app.models.user import User
from tests.conftest import TEST_DATABASE_URL, assign_user_to_project, auth_header


async def _create_task(
    client: httpx.AsyncClient,
    header: str,
    project_id: uuid.UUID,
    name: str,
    start: str = "2026-01-01",
    end: str = "2026-02-01",
    depends_on: str | None = None,
) -> dict:
    body = {"name": name, "start_date": start, "end_date": end}
    if depends_on is not None:
        body["depends_on_id"] = depends_on
    resp = await client.post(
        f"/api/v1/projects/{project_id}/tasks",
        headers={"Authorization": header},
        json=body,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


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


# --- M7: date-order validation on update ------------------------------------


@pytest.mark.asyncio
async def test_update_end_before_start_rejected(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    task = await _create_task(client, header, test_project.id, "Masonry")

    # Both dates moved so end < start -> 422 at the schema boundary.
    both = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{task['id']}",
        headers={"Authorization": header},
        json={"start_date": "2026-03-01", "end_date": "2026-02-01"},
    )
    assert both.status_code == 422

    # Partial updates crossing the persisted date -> 422 after the merge.
    end_only = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{task['id']}",
        headers={"Authorization": header},
        json={"end_date": "2025-12-01"},
    )
    assert end_only.status_code == 422

    start_only = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{task['id']}",
        headers={"Authorization": header},
        json={"start_date": "2026-03-01"},
    )
    assert start_only.status_code == 422

    # A rejected update must not have mutated the persisted row.
    current = (
        await client.get(
            f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header}
        )
    ).json()
    assert current[0]["start_date"] == "2026-01-01"
    assert current[0]["end_date"] == "2026-02-01"


# --- M7: dependency integrity on update -------------------------------------


@pytest.mark.asyncio
async def test_update_dependency_integrity(
    client: httpx.AsyncClient,
    test_db: AsyncSession,
    test_admin_user: User,
    test_project: Project,
):
    header = await auth_header(client, "admin@test.com")
    task = await _create_task(client, header, test_project.id, "Task A")

    url = f"/api/v1/projects/{test_project.id}/tasks/{task['id']}"

    missing = await client.patch(
        url,
        headers={"Authorization": header},
        json={"depends_on_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing.status_code == 400

    self_dep = await client.patch(
        url, headers={"Authorization": header}, json={"depends_on_id": task["id"]}
    )
    assert self_dep.status_code == 400

    # A task from another project must be rejected too.
    other = Project(
        project_code="PRJ-TEST-0002",
        name="Other Residence",
        site_address="456 Other Street",
        client_name="Other Client Co.",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        budget_total=500000,
    )
    test_db.add(other)
    await test_db.commit()
    await test_db.refresh(other)
    foreign_task = await _create_task(client, header, other.id, "Foreign Task")

    cross_project = await client.patch(
        url, headers={"Authorization": header}, json={"depends_on_id": foreign_task["id"]}
    )
    assert cross_project.status_code == 400

    # None of the rejected updates may have stuck.
    current = (
        await client.get(
            f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header}
        )
    ).json()
    assert current[0]["depends_on_id"] is None


@pytest.mark.asyncio
async def test_link_valid_dependency_and_clear_it(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    a = await _create_task(client, header, test_project.id, "Framing")
    b = await _create_task(client, header, test_project.id, "Roofing")

    linked = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": header},
        json={"depends_on_id": b["id"]},
    )
    assert linked.status_code == 200
    assert linked.json()["depends_on_id"] == b["id"]

    cleared = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{a['id']}",
        headers={"Authorization": header},
        json={"depends_on_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["depends_on_id"] is None


# --- M7: dependency-cycle detection -----------------------------------------


@pytest.mark.asyncio
async def test_dependency_cycles_rejected(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    b = await _create_task(client, header, test_project.id, "Foundation")
    c = await _create_task(client, header, test_project.id, "Slab", depends_on=b["id"])
    a = await _create_task(client, header, test_project.id, "Framing", depends_on=c["id"])
    url = f"/api/v1/projects/{test_project.id}/tasks"

    # Two-node cycle: X -> Y, then Y.depends_on = X.
    two_node = await client.patch(
        f"{url}/{b['id']}", headers={"Authorization": header}, json={"depends_on_id": c["id"]}
    )
    assert two_node.status_code == 400

    # Three-node cycle: closing A -> C -> B back to A.
    three_node = await client.patch(
        f"{url}/{b['id']}", headers={"Authorization": header}, json={"depends_on_id": a["id"]}
    )
    assert three_node.status_code == 400

    current = (await client.get(url, headers={"Authorization": header})).json()
    by_name = {t["name"]: t for t in current}
    assert by_name["Foundation"]["depends_on_id"] is None
    assert by_name["Slab"]["depends_on_id"] == b["id"]
    assert by_name["Framing"]["depends_on_id"] == c["id"]


@pytest.mark.asyncio
async def test_cycle_broken_by_delete_then_link_allowed(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}/tasks"
    x = await _create_task(client, header, test_project.id, "X")
    y = await _create_task(client, header, test_project.id, "Y", depends_on=x["id"])

    blocked = await client.patch(
        f"{url}/{x['id']}", headers={"Authorization": header}, json={"depends_on_id": y["id"]}
    )
    assert blocked.status_code == 400

    await client.delete(f"{url}/{y['id']}", headers={"Authorization": header})
    z = await _create_task(client, header, test_project.id, "Z")

    allowed = await client.patch(
        f"{url}/{x['id']}", headers={"Authorization": header}, json={"depends_on_id": z["id"]}
    )
    assert allowed.status_code == 200
    assert allowed.json()["depends_on_id"] == z["id"]


# --- M7: concurrency (project row lock serializes task writes) ---------------


@pytest.fixture
async def concurrent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Per-request DB session so two task PATCHes race for real."""
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
async def test_concurrent_opposing_links_cannot_form_a_cycle(
    concurrent_client: httpx.AsyncClient,
    test_admin_user: User,
    test_project: Project,
):
    """A->B and B->A in flight at once: the project row lock lets exactly one
    commit; the loser sees the committed edge and is rejected, so the graph
    can never contain a cycle."""
    header = await auth_header(concurrent_client, "admin@test.com")
    a = await _create_task(concurrent_client, header, test_project.id, "A")
    b = await _create_task(concurrent_client, header, test_project.id, "B")
    url = f"/api/v1/projects/{test_project.id}/tasks"

    async def link_a_to_b() -> httpx.Response:
        return await concurrent_client.patch(
            f"{url}/{a['id']}", headers={"Authorization": header}, json={"depends_on_id": b["id"]}
        )

    async def link_b_to_a() -> httpx.Response:
        return await concurrent_client.patch(
            f"{url}/{b['id']}", headers={"Authorization": header}, json={"depends_on_id": a["id"]}
        )

    responses = await asyncio.gather(link_a_to_b(), link_b_to_a())
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 400], [r.text for r in responses]

    tasks = (await concurrent_client.get(url, headers={"Authorization": header})).json()
    links = {t["name"]: t["depends_on_id"] for t in tasks}
    assert (links["A"] == b["id"]) != (links["B"] == a["id"])

