"""
M14 — vendor master-data tests.

Covers vendor CRUD over the real ASGI client: create/update/deactivate/read,
duplicate-name 409, email validation, RBAC (admin + procurement only; S/C 403),
audit rows, and M8 idempotent create replay.
"""
import uuid
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.user import User
from tests.conftest import TEST_DATABASE_URL, auth_header


def vendor_payload(**overrides):
    payload = {
        "name": "Apex Cement Works",
        "contact_name": "Raj",
        "email": "sales@apexcement.example",
        "phone": "555-0100",
        "payment_terms": "NET 30",
        "address": "42 Industrial Rd",
        "notes": "Preferred cement supplier",
    }
    payload.update(overrides)
    return payload


async def create_vendor(
    client: httpx.AsyncClient, header: str, **overrides
) -> httpx.Response:
    return await client.post(
        "/api/v1/vendors", headers={"Authorization": header}, json=vendor_payload(**overrides)
    )


async def audit_actions_for(
    db: AsyncSession, action: str, record_id: str | None = None
) -> list[AuditLog]:
    stmt = select(AuditLog).where(AuditLog.action == action)
    if record_id is not None:
        stmt = stmt.where(AuditLog.record_id == record_id)
    return list((await db.execute(stmt)).scalars().all())


@pytest.fixture
async def per_request_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Per-request DB session (like production) so a failed request tears its
    transaction down before the retry runs."""
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


# --- Create / read ------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_creates_vendor(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    resp = await create_vendor(client, header)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Apex Cement Works"
    assert body["contact_name"] == "Raj"
    assert body["email"] == "sales@apexcement.example"
    assert body["payment_terms"] == "NET 30"
    assert body["is_active"] is True
    assert body["id"]

    listed = (await client.get("/api/v1/vendors", headers={"Authorization": header})).json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]

    single = (
        await client.get(f"/api/v1/vendors/{body['id']}", headers={"Authorization": header})
    ).json()
    assert single["name"] == "Apex Cement Works"


@pytest.mark.asyncio
async def test_procurement_can_create_and_list(
    client: httpx.AsyncClient, test_procurement_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "procurement@test.com")
    resp = await create_vendor(client, header, name="Steel Co")
    assert resp.status_code == 201, resp.text
    listed = (await client.get("/api/v1/vendors", headers={"Authorization": header})).json()
    assert [v["name"] for v in listed] == ["Steel Co"]


@pytest.mark.asyncio
async def test_duplicate_vendor_name_409(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    first = await create_vendor(client, header)
    assert first.status_code == 201
    dup = await create_vendor(client, header, contact_name="Someone else")
    assert dup.status_code == 409
    assert "already exists" in dup.json()["detail"]

    listed = (await client.get("/api/v1/vendors", headers={"Authorization": header})).json()
    assert len(listed) == 1


@pytest.mark.asyncio
async def test_get_vendor_404(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    resp = await client.get(
        f"/api/v1/vendors/{uuid.uuid4()}", headers={"Authorization": header}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_vendor_email_422(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    resp = await create_vendor(client, header, email="not-an-email")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_name_422(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        "/api/v1/vendors",
        headers={"Authorization": header},
        json={"contact_name": "No Name"},
    )
    assert resp.status_code == 422


# --- RBAC ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervisor_and_client_403(
    client: httpx.AsyncClient,
    test_admin_user: User,
    test_supervisor_user: User,
    test_client_user: User,
    test_db: AsyncSession,
):
    admin = await auth_header(client, "admin@test.com")
    await create_vendor(client, admin)
    sup = await auth_header(client, "supervisor@test.com")
    cli = await auth_header(client, "client@test.com")

    for header in (sup, cli):
        assert (await client.get("/api/v1/vendors", headers={"Authorization": header})).status_code == 403
        assert (await client.post(
            "/api/v1/vendors", headers={"Authorization": header}, json=vendor_payload()
        )).status_code == 403

    vid = (await client.get("/api/v1/vendors", headers={"Authorization": admin})).json()[0]["id"]
    for header in (sup, cli):
        assert (await client.get(
            f"/api/v1/vendors/{vid}", headers={"Authorization": header}
        )).status_code == 403
        assert (await client.patch(
            f"/api/v1/vendors/{vid}",
            headers={"Authorization": header},
            json={"notes": "x"},
        )).status_code == 403


# --- Update / soft deactivation ------------------------------------------------


@pytest.mark.asyncio
async def test_update_and_soft_deactivate(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    v = (await create_vendor(client, header)).json()

    updated = (await client.patch(
        f"/api/v1/vendors/{v['id']}",
        headers={"Authorization": header},
        json={"payment_terms": "NET 60", "notes": None},
    )).json()
    assert updated["payment_terms"] == "NET 60"
    assert updated["notes"] is None
    assert updated["is_active"] is True

    deactivated = (await client.patch(
        f"/api/v1/vendors/{v['id']}",
        headers={"Authorization": header},
        json={"is_active": False},
    )).json()
    assert deactivated["is_active"] is False

    # Still readable (deactivation never hides the row).
    single = (await client.get(
        f"/api/v1/vendors/{v['id']}", headers={"Authorization": header}
    )).json()
    assert single["is_active"] is False

    reactivated = (await client.patch(
        f"/api/v1/vendors/{v['id']}",
        headers={"Authorization": header},
        json={"is_active": True},
    )).json()
    assert reactivated["is_active"] is True


@pytest.mark.asyncio
async def test_rename_to_duplicate_409(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    await create_vendor(client, header, name="Vendor A")
    b = (await create_vendor(client, header, name="Vendor B")).json()

    resp = await client.patch(
        f"/api/v1/vendors/{b['id']}",
        headers={"Authorization": header},
        json={"name": "Vendor A"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_vendor_404(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    resp = await client.patch(
        f"/api/v1/vendors/{uuid.uuid4()}",
        headers={"Authorization": header},
        json={"notes": "x"},
    )
    assert resp.status_code == 404


# --- Audit ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vendor_writes_are_audited(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    v = (await create_vendor(client, header)).json()
    assert await audit_actions_for(test_db, "vendor_create", v["id"])

    await client.patch(
        f"/api/v1/vendors/{v['id']}",
        headers={"Authorization": header},
        json={"payment_terms": "NET 45"},
    )
    assert await audit_actions_for(test_db, "vendor_update", v["id"])


# --- Idempotency ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_vendor_create_replay(
    client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    header = await auth_header(client, "admin@test.com")
    url = "/api/v1/vendors"
    body = vendor_payload(name="Idempotent Co")
    key = "key-vendor-0001"

    first = await client.post(
        url, headers={"Authorization": header, "Idempotency-Key": key}, json=body
    )
    assert first.status_code == 201
    replay = await client.post(
        url, headers={"Authorization": header, "Idempotency-Key": key}, json=body
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    listed = (await client.get(url, headers={"Authorization": header})).json()
    assert len(listed) == 1

    # Reusing the key for a different body is a 409, never a wrong replay.
    conflict = await client.post(
        url,
        headers={"Authorization": header, "Idempotency-Key": key},
        json=vendor_payload(name="Idempotent Co", payment_terms="NET 10"),
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_idempotent_vendor_create_key_freed_after_failure(
    per_request_client: httpx.AsyncClient, test_admin_user: User, test_db: AsyncSession
):
    """A failed create (duplicate) rolls the claim back, so the same key can be
    retried with a corrected body. Uses per-request sessions (like production)
    so the failed request's transaction is torn down before the retry."""
    header = await auth_header(per_request_client, "admin@test.com")
    await create_vendor(per_request_client, header, name="Busy Co")
    key = "key-vendor-0002"

    dup = await per_request_client.post(
        "/api/v1/vendors",
        headers={"Authorization": header, "Idempotency-Key": key},
        json=vendor_payload(name="Busy Co"),
    )
    assert dup.status_code == 409

    ok = await per_request_client.post(
        "/api/v1/vendors",
        headers={"Authorization": header, "Idempotency-Key": key},
        json=vendor_payload(name="Retried Co"),
    )
    assert ok.status_code == 201
    assert ok.json()["name"] == "Retried Co"
