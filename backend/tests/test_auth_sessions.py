"""
M9 — refresh-token security: rotation, server-side revocation, deactivated-user
cutoff, reuse/theft detection, and auth-event auditing.

Login issues an opaque refresh token backed by a `refresh_sessions` row (only a
SHA-256 digest is stored). Every refresh rotates: the presented token is
revoked ('rotated') and a child session is issued in the same family. Reuse of
a dead token revokes the whole family (theft signal). Deactivation revokes all
sessions. Concurrency tests use two real DB connections (per-request sessions,
the established M5/M7/M8 pattern) — never a fake sequential race.
"""
import hashlib
import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import get_db
from app.core.security import hash_password
from app.main import app
from app.models.audit import AuditLog
from app.models.refresh_session import RefreshSession
from app.models.user import User, UserRole
from tests.conftest import TEST_DATABASE_URL, auth_header


async def _login(client: httpx.AsyncClient, email: str = "admin@test.com") -> dict:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "TestPass123"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _refresh(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": token})


async def _sessions(db: AsyncSession) -> list[RefreshSession]:
    result = await db.execute(select(RefreshSession).order_by(RefreshSession.issued_at))
    return list(result.scalars().all())


# --- basic lifecycle ---------------------------------------------------------


@pytest.mark.asyncio
async def test_login_creates_session_row(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """M9 req: each issued refresh token has a server-side record."""
    await _login(client)
    sessions = await _sessions(test_db)
    assert len(sessions) == 1
    assert sessions[0].user_id == test_admin_user.id
    assert sessions[0].revoked_at is None


@pytest.mark.asyncio
async def test_only_hash_of_token_stored(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """M9 req: raw refresh tokens are never persisted — only the SHA-256 hash."""
    data = await _login(client)
    sessions = await _sessions(test_db)
    stored = sessions[0].token_hash
    assert stored != data["refresh_token"]
    assert len(stored) == 64
    assert stored == hashlib.sha256(data["refresh_token"].encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_refresh_succeeds_and_returns_pair(client: httpx.AsyncClient, test_admin_user: User):
    data = await _login(client)
    resp = await _refresh(client, data["refresh_token"])
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_refresh_rotates_token(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """M9 req: every refresh issues a new refresh token and invalidates the old one."""
    data = await _login(client)
    resp = await _refresh(client, data["refresh_token"])
    assert resp.status_code == 200
    new_token = resp.json()["refresh_token"]
    assert new_token != data["refresh_token"]

    sessions = await _sessions(test_db)
    assert len(sessions) == 2
    old, new = sessions[0], sessions[1]
    assert old.revoked_at is not None and old.revoked_reason == "rotated"
    assert new.revoked_at is None
    assert new.parent_id == old.id          # rotation relationship
    assert new.family_id == old.family_id   # same family


@pytest.mark.asyncio
async def test_old_token_rejected_after_rotation(client: httpx.AsyncClient, test_admin_user: User):
    data = await _login(client)
    await _refresh(client, data["refresh_token"])
    resp = await _refresh(client, data["refresh_token"])
    assert resp.status_code == 401
    assert "Invalid refresh token" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_new_token_works_after_rotation(client: httpx.AsyncClient, test_db, test_admin_user: User):
    data = await _login(client)
    resp = await _refresh(client, data["refresh_token"])
    new_token = resp.json()["refresh_token"]
    assert (await _refresh(client, new_token)).status_code == 200
    sessions = await _sessions(test_db)
    assert sum(1 for s in sessions if s.revoked_at is None) == 1  # only the latest lives


@pytest.mark.asyncio
async def test_unknown_token_rejected(client: httpx.AsyncClient):
    resp = await _refresh(client, "not-a-real-token")
    assert resp.status_code == 401
    assert "Invalid refresh token" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_malformed_token_rejected(client: httpx.AsyncClient):
    """Malformed (non-token) input resolves to an unknown hash -> same generic 401."""
    resp = await _refresh(client, "garbage{not-a-token}")
    assert resp.status_code == 401


# --- revocation / logout -----------------------------------------------------


@pytest.mark.asyncio
async def test_logout_revokes_session(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """M9 req: POST /auth/logout revokes the refresh session server-side."""
    data = await _login(client)
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 204

    sessions = await _sessions(test_db)
    assert all(s.revoked_at is not None for s in sessions)
    assert sessions[0].revoked_reason == "logout"

    assert (await _refresh(client, data["refresh_token"])).status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_rotated_family(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """Logging out with a rotated (already-dead) token still kills the active chain."""
    data = await _login(client)
    rotated = (await _refresh(client, data["refresh_token"])).json()["refresh_token"]
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]})
    assert resp.status_code == 204
    assert (await _refresh(client, rotated)).status_code == 401


@pytest.mark.asyncio
async def test_logout_with_unknown_token_is_idempotent(client: httpx.AsyncClient):
    resp = await client.post("/api/v1/auth/logout", json={"refresh_token": "unknown-token"})
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_revoked_token_cannot_refresh(client: httpx.AsyncClient, test_db, test_admin_user: User):
    data = await _login(client)
    await client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]})
    assert (await _refresh(client, data["refresh_token"])).status_code == 401


@pytest.mark.asyncio
async def test_expired_token_cannot_refresh(client: httpx.AsyncClient, test_db, test_admin_user: User):
    data = await _login(client)
    (await _sessions(test_db))[0].expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await test_db.commit()
    assert (await _refresh(client, data["refresh_token"])).status_code == 401


# --- reuse / theft detection -------------------------------------------------


async def _backdate_revocation(db: AsyncSession, session_id, seconds: int = 300) -> None:
    """Simulate a rotation that happened long ago so reuse is past the grace window."""
    (await _sessions(db))[0].revoked_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    await db.commit()


@pytest.mark.asyncio
async def test_reuse_of_rotated_token_within_grace_is_benign(
    client: httpx.AsyncClient, test_db, test_admin_user: User
):
    """Reuse of an old rotated token within the grace window (a two-tab race) is
    rejected without nuking the winner's session."""
    data = await _login(client)
    new_token = (await _refresh(client, data["refresh_token"])).json()["refresh_token"]

    assert (await _refresh(client, data["refresh_token"])).status_code == 401  # benign reject
    assert (await _refresh(client, new_token)).status_code == 200             # family survived


@pytest.mark.asyncio
async def test_reuse_after_grace_revokes_family(
    client: httpx.AsyncClient, test_db, test_admin_user: User
):
    """Reuse of an old rotated token past the grace window is treated as theft:
    the whole family (incl. the newest token the victim is using) is revoked."""
    data = await _login(client)
    new_token = (await _refresh(client, data["refresh_token"])).json()["refresh_token"]

    await _backdate_revocation(test_db, 0)  # the old 'rotated' row is now stale
    assert (await _refresh(client, data["refresh_token"])).status_code == 401  # reuse
    assert (await _refresh(client, new_token)).status_code == 401             # family dead

    sessions = await _sessions(test_db)
    assert all(s.revoked_at is not None for s in sessions)
    reasons = {s.revoked_reason for s in sessions}
    assert "reuse_detected" in reasons  # the active child was killed as theft


# --- deactivated-user cutoff -------------------------------------------------


@pytest.mark.asyncio
async def test_deactivated_user_cannot_refresh(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """M9 req: deactivation after issue cuts off refresh without waiting for JWT expiry."""
    data = await _login(client)
    header = await auth_header(client, "admin@test.com")
    resp = await client.patch(
        f"/api/v1/users/{test_admin_user.id}",
        headers={"Authorization": header},
        json={"is_active": False},
    )
    assert resp.status_code == 200

    assert (await _refresh(client, data["refresh_token"])).status_code == 401

    sessions = await _sessions(test_db)
    assert all(s.revoked_at is not None and s.revoked_reason == "user_deactivated" for s in sessions)


@pytest.mark.asyncio
async def test_reactivation_requires_relogin(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """Existing user model is a bare is_active flag; reactivation restores login
    but the deactivation-time revocation keeps old sessions dead."""
    actor = User(
        email="admin2@test.com",
        full_name="Admin Two",
        hashed_password=hash_password("TestPass123"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    test_db.add(actor)
    await test_db.commit()

    data = await _login(client)
    header = await auth_header(client, "admin2@test.com")  # deactivated admins can't PATCH
    await client.patch(
        f"/api/v1/users/{test_admin_user.id}", headers={"Authorization": header}, json={"is_active": False}
    )
    assert (await _refresh(client, data["refresh_token"])).status_code == 401

    resp = await client.patch(
        f"/api/v1/users/{test_admin_user.id}", headers={"Authorization": header}, json={"is_active": True}
    )
    assert resp.status_code == 200 and resp.json()["is_active"] is True

    # Old refresh token stays dead (revoked at deactivation); login is restored.
    assert (await _refresh(client, data["refresh_token"])).status_code == 401
    await _login(client)


# --- auth-event auditing -----------------------------------------------------


@pytest.mark.asyncio
async def test_auth_events_recorded(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """M9 req: login, refresh and logout events land in audit_logs."""
    data = await _login(client)
    await _refresh(client, data["refresh_token"])
    await client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]})

    result = await test_db.execute(
        select(AuditLog).where(AuditLog.table_name == "auth").order_by(AuditLog.created_at)
    )
    rows = list(result.scalars().all())
    actions = [r.action for r in rows]
    assert actions == ["login", "refresh", "logout"], actions
    assert all(r.user_id == test_admin_user.id for r in rows)


@pytest.mark.asyncio
async def test_auth_events_contain_ip(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """audit_logs.ip_address (String(45), nullable) is populated for auth events."""
    data = await _login(client)
    await _refresh(client, data["refresh_token"])
    await client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]})

    result = await test_db.execute(select(AuditLog).where(AuditLog.table_name == "auth"))
    rows = list(result.scalars().all())
    assert rows
    assert all(r.ip_address is not None for r in rows)


@pytest.mark.asyncio
async def test_reuse_detection_is_audited(client: httpx.AsyncClient, test_db, test_admin_user: User):
    data = await _login(client)
    await _refresh(client, data["refresh_token"])
    await _backdate_revocation(test_db, 0)  # push the rotated row past the grace window
    await _refresh(client, data["refresh_token"])  # theft -> family revocation

    result = await test_db.execute(select(AuditLog).where(AuditLog.table_name == "auth"))
    rows = list(result.scalars().all())
    assert any(r.action == "refresh_reuse_detected" for r in rows)


# --- concurrency (two real DB connections, per-request sessions) -------------


@pytest.fixture
async def concurrent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Per-request DB session so two refreshes genuinely race on separate connections."""
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
async def test_concurrent_refresh_executes_exactly_once(
    concurrent_client: httpx.AsyncClient, test_admin_user: User
):
    """Two simultaneous refreshes of the same token: exactly one wins via the row lock."""
    data = await _login(concurrent_client)
    old_token = data["refresh_token"]

    responses = await asyncio.gather(
        _refresh(concurrent_client, old_token), _refresh(concurrent_client, old_token)
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 401], [r.text for r in responses]

    winner = next(r for r in responses if r.status_code == 200)
    new_token = winner.json()["refresh_token"]
    assert new_token != old_token

    # Winner's token is the only live one; the old token stays dead.
    assert (await _refresh(concurrent_client, new_token)).status_code == 200
    assert (await _refresh(concurrent_client, old_token)).status_code == 401


@pytest.mark.asyncio
async def test_concurrent_old_token_reuse_is_safe(
    concurrent_client: httpx.AsyncClient, test_admin_user: User
):
    """Simultaneous reuse of the OLD token right after rotation is the benign
    race case: both are rejected (no double success, no session loss) and the
    newest token keeps working."""
    data = await _login(concurrent_client)
    old_token = data["refresh_token"]
    first = await _refresh(concurrent_client, old_token)
    assert first.status_code == 200
    new_token = first.json()["refresh_token"]

    responses = await asyncio.gather(
        _refresh(concurrent_client, old_token), _refresh(concurrent_client, old_token)
    )
    assert [r.status_code for r in responses] == [401, 401], [r.text for r in responses]

    # Winner's session is untouched by the race.
    assert (await _refresh(concurrent_client, new_token)).status_code == 200
    assert (await _refresh(concurrent_client, old_token)).status_code == 401


@pytest.mark.asyncio
async def test_concurrent_refresh_and_logout_deterministic(
    concurrent_client: httpx.AsyncClient, test_admin_user: User
):
    """A refresh racing a logout of the same token settles consistently: the token
    can never be usable afterwards, and if the refresh won its rotated child also
    ends up dead (logout revokes the fork)."""
    data = await _login(concurrent_client)
    token = data["refresh_token"]

    async def refresh() -> httpx.Response:
        return await _refresh(concurrent_client, token)

    async def logout() -> httpx.Response:
        return await concurrent_client.post("/api/v1/auth/logout", json={"refresh_token": token})

    responses = await asyncio.gather(refresh(), logout())

    for r in responses:
        assert r.status_code in (200, 204, 401), r.text

    rotated = next(
        (r.json()["refresh_token"] for r in responses if r.status_code == 200), None
    )
    if rotated is not None:
        assert (await _refresh(concurrent_client, rotated)).status_code == 401

    assert (await _refresh(concurrent_client, token)).status_code == 401