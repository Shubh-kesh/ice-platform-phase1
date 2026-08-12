"""
M11 — Google Sign-In & user onboarding tests.

Covers the full flow end-to-end against the real app + Postgres: authorize ->
callback -> link/lookup -> M9 session, plus the §7 link matrix (existing
user, invite, email drift, deactivated, unknown email), rejection paths
(signature/iss/aud/exp/nonce/email_verified), M9 rotation/logout after a
Google login, distinct audit actions, and the concurrent first-time-link race.

The ID token is produced by a scratch RSA keypair (`google_jwks` fixture): the
test serves the public key as the cert source and signs claims with the private
key, so `verify_google_id_token` runs its real RS256 signature/iss/aud/exp/
nonce verification path with zero network. The token exchange is similarly
stubbed to return the signed ID token.
"""
import asyncio
import base64
import hashlib
import time
import uuid
from typing import AsyncGenerator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import get_db
from app.services.google_auth import verify_google_id_token
from app.main import app
from app.models.audit import AuditLog
from app.models.refresh_session import RefreshSession
from app.models.user import User
from tests.conftest import TEST_DATABASE_URL, auth_header

AUDIENCE = "ci-test-client.apps.googleusercontent.com"
INVITE_EMAIL = "invitee@example.com"
SUPER_EMAIL = "supervisor@test.com"


def _claims(
    authz_nonce: str,
    sub: str,
    email: str,
    *,
    email_verified: bool = True,
    aud: str = AUDIENCE,
    iss: str = "accounts.google.com",
    exp_delta: int = 3600,
    name: str = "Google Test User",
    at_hash: str | None = None,
) -> dict:
    now = int(time.time())
    claims = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
        "name": name,
        "iat": now - 5,
        "nbf": now - 5,
        "exp": now + exp_delta,
        "nonce": authz_nonce,
    }
    if at_hash is not None:
        claims["at_hash"] = at_hash
    return claims


def _patch_google(monkeypatch, google_jwks, token: str) -> None:
    """Serve the test certs + scripted token exchange for the callback flow."""
    monkeypatch.setattr(
        "app.services.google_auth._fetch_google_certs", lambda: google_jwks["certs"]
    )
    monkeypatch.setattr(
        "app.services.google_auth.exchange_code_for_tokens",
        lambda code, verifier: {"id_token": token},
    )


async def _authorize(client: httpx.AsyncClient) -> dict:
    resp = await client.get("/api/v1/auth/google/authorize")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _google_callback(client: httpx.AsyncClient, authz: dict, code: str = "auth-code-1") -> httpx.Response:
    return await client.post(
        "/api/v1/auth/google/callback",
        json={"code": code, "code_verifier": authz["code_verifier"], "state": authz["state"]},
    )


async def _create_invite(client: httpx.AsyncClient, email: str, role: str = "client") -> dict:
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={"email": email, "full_name": "Invited User", "role": role, "google_only": True},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _audit_actions(db: AsyncSession) -> list[str]:
    result = await db.execute(select(AuditLog).order_by(AuditLog.created_at))
    return [r.action for r in result.scalars().all()]


async def _refresh(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post("/api/v1/auth/refresh", json={"refresh_token": token})


# --- authorize endpoint -------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_returns_flow_parameters(client: httpx.AsyncClient):
    authz = await _authorize(client)
    assert authz["authorize_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=" + AUDIENCE in authz["authorize_url"]
    assert "code_challenge_method=S256" in authz["authorize_url"]
    assert "nonce=" in authz["authorize_url"]
    assert authz["state"]
    assert authz["code_verifier"]
    assert authz["nonce"]


@pytest.mark.asyncio
async def test_authorize_disabled_without_config(client: httpx.AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")
    resp = await client.get("/api/v1/auth/google/authorize")
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


def test_id_token_verification_accepts_google_rsa_jwk(google_jwks):
    """Regression: Google's current JWKS publishes RSA n/e, not x5c."""
    nonce = "n" * 32
    token = google_jwks["sign"](_claims(nonce, "google-jwk", "jwk@example.com"))
    claims = verify_google_id_token(
        token,
        expected_nonce=nonce,
        expected_aud=AUDIENCE,
        certs_source=lambda: google_jwks["jwks"],
    )
    assert claims["sub"] == "google-jwk"


def test_id_token_with_at_hash_claim_verifies(google_jwks):
    """Regression: real Google ID tokens carry `at_hash`; we do not use the
    exchange access token, so verification must not require it (matching
    google.oauth2.id_token.verify_oauth2_token)."""
    access_token = "fake-access-token"
    at_hash = base64.urlsafe_b64encode(hashlib.sha256(access_token.encode()).digest()[:16]).rstrip(b"=").decode("ascii")
    nonce = "n" * 32
    token = google_jwks["sign"](
        _claims(nonce, "google-at-hash", "athash@example.com", at_hash=at_hash)
    )
    claims = verify_google_id_token(
        token,
        expected_nonce=nonce,
        expected_aud=AUDIENCE,
        certs_source=lambda: google_jwks["jwks"],
    )
    assert claims["sub"] == "google-at-hash"


# --- invite -> link -> session (scenarios F/A, §13.1) ------------------------


@pytest.mark.asyncio
async def test_invited_user_links_on_callback_and_gets_m9_session(
    client: httpx.AsyncClient, test_db, test_admin_user, google_jwks, monkeypatch
):
    invite = await _create_invite(client, INVITE_EMAIL, role="procurement_manager")
    assert invite["google_linked"] is False
    assert invite["has_password"] is False

    authz = await _authorize(client)
    sub = "google-sub-invite-1"
    token = google_jwks["sign"](_claims(authz["nonce"], sub, INVITE_EMAIL, name="Invited User"))
    _patch_google(monkeypatch, google_jwks, token)

    resp = await _google_callback(client, authz)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]

    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    me_data = me.json()
    assert me_data["email"] == INVITE_EMAIL
    assert me_data["role"] == "procurement_manager"
    assert me_data["google_linked"] is True
    assert me_data["has_password"] is False
    assert me_data["google_email"] == INVITE_EMAIL

    actions = await _audit_actions(test_db)
    assert "user_invited" in actions
    assert "account_linked" in actions
    assert "google_login" in actions

    # auth events carry the request IP (§13.11)
    result = await test_db.execute(select(AuditLog).where(AuditLog.table_name == "auth"))
    assert all(r.ip_address is not None for r in result.scalars().all())

    # M9 session: refresh rotates, logout revokes the family (§13.8)
    rotated = await _refresh(client, body["refresh_token"])
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != body["refresh_token"]
    assert (await _refresh(client, body["refresh_token"])).status_code == 401
    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": rotated.json()["refresh_token"]})
    assert logout.status_code == 204
    assert (await _refresh(client, rotated.json()["refresh_token"])).status_code == 401


# --- existing users: link + preservation (scenarios A, B; §13.2, §13.7) -------


@pytest.mark.asyncio
async def test_existing_local_user_links_keeping_role_and_password(
    client: httpx.AsyncClient, test_db, test_supervisor_user, google_jwks, monkeypatch
):
    authz = await _authorize(client)
    token = google_jwks["sign"](_claims(authz["nonce"], "google-sub-super", SUPER_EMAIL))
    _patch_google(monkeypatch, google_jwks, token)

    resp = await _google_callback(client, authz)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["role"] == "site_supervisor"
    assert me.json()["google_linked"] is True
    assert me.json()["has_password"] is True  # existing password kept (§7/A)

    actions = await _audit_actions(test_db)
    assert "account_linked" in actions
    assert "google_login" in actions

    # Password login still works after linking — the password path is untouched.
    pw = await client.post(
        "/api/v1/auth/login", json={"email": SUPER_EMAIL, "password": "TestPass123"}
    )
    assert pw.status_code == 200


@pytest.mark.asyncio
async def test_existing_google_user_re_signin_is_plain_login(
    client: httpx.AsyncClient, test_db, test_admin_user, google_jwks, monkeypatch
):
    for i in range(2):
        authz = await _authorize(client)
        token = google_jwks["sign"](_claims(authz["nonce"], "google-sub-b", f"backer{i}@example.com"))
        _patch_google(monkeypatch, google_jwks, token)
        # First sign-in links a fresh account, second is scenario B.
        if i == 0:
            await _create_invite(client, f"backer{i}@example.com", role="client")
        resp = await _google_callback(client, authz)
        assert resp.status_code == 200, resp.text

    # Two google_logins, but only ONE account_linked across the whole flow.
    result = await test_db.execute(select(AuditLog).where(AuditLog.action == "google_login"))
    assert len(list(result.scalars().all())) == 2
    result = await test_db.execute(select(AuditLog).where(AuditLog.action == "account_linked"))
    assert len(list(result.scalars().all())) == 1


# --- RBAC / assignment preservation (§13.7) -----------------------------------


@pytest.mark.asyncio
async def test_role_and_project_access_preserved_after_google_login(
    client: httpx.AsyncClient, test_db, test_supervisor_user, test_project, google_jwks, monkeypatch
):
    from tests.conftest import assign_user_to_project

    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)

    authz = await _authorize(client)
    token = google_jwks["sign"](_claims(authz["nonce"], "google-sub-super-2", SUPER_EMAIL))
    _patch_google(monkeypatch, google_jwks, token)
    resp = await _google_callback(client, authz)
    assert resp.status_code == 200

    projects = await client.get(
        "/api/v1/projects", headers={"Authorization": f"Bearer {resp.json()['access_token']}"}
    )
    assert projects.status_code == 200
    ids = [p["id"] for p in projects.json()]
    assert str(test_project.id) in ids  # assignment survived the Google link


# --- rejection paths (§13.3-6) ------------------------------------------------


@pytest.mark.asyncio
async def test_unverified_email_rejected(
    client: httpx.AsyncClient, test_db, test_admin_user, google_jwks, monkeypatch
):
    invite = await _create_invite(client, INVITE_EMAIL)
    authz = await _authorize(client)
    token = google_jwks["sign"](
        _claims(authz["nonce"], "google-sub-unv", INVITE_EMAIL, email_verified=False)
    )
    _patch_google(monkeypatch, google_jwks, token)

    resp = await _google_callback(client, authz)
    assert resp.status_code == 401
    # The invitee got no session (only the admin's login session exists).
    result = await test_db.execute(
        select(RefreshSession).where(RefreshSession.user_id == uuid.UUID(invite["id"]))
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_unknown_email_rejected_no_public_signup(
    client: httpx.AsyncClient, test_db, google_jwks, monkeypatch
):
    authz = await _authorize(client)
    token = google_jwks["sign"](_claims(authz["nonce"], "google-sub-stranger", "stranger@example.com"))
    _patch_google(monkeypatch, google_jwks, token)
    resp = await _google_callback(client, authz)
    assert resp.status_code == 403
    assert "No ICE account found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_id_tokens_rejected(
    client: httpx.AsyncClient, test_db, test_admin_user, google_jwks, monkeypatch
):
    """Wrong signature / audience / issuer / expiry / nonce -> 401, no session."""
    authz = await _authorize(client)
    _patch_google(monkeypatch, google_jwks, "not-an-id-token")

    bad = await _google_callback(client, authz)
    assert bad.status_code == 401

    cases = [
        _claims(authz["nonce"], "sub-x", "ghost@example.com", aud="some-other-client"),
        _claims(authz["nonce"], "sub-x", "ghost@example.com", iss="https://evil.example"),
        _claims(authz["nonce"], "sub-x", "ghost@example.com", exp_delta=-3600),
        _claims("a-different-nonce", "sub-x", "ghost@example.com"),
    ]
    for claims in cases:
        good = google_jwks["sign"](claims)
        _patch_google(monkeypatch, google_jwks, good)
        resp = await _google_callback(client, authz)
        assert resp.status_code == 401, claims

    result = await test_db.execute(select(RefreshSession))
    assert result.scalars().all() == []
    assert "account_linked" not in await _audit_actions(test_db)


@pytest.mark.asyncio
async def test_bad_state_rejected(client: httpx.AsyncClient, google_jwks, monkeypatch):
    _patch_google(monkeypatch, google_jwks, "irrelevant")
    resp = await client.post(
        "/api/v1/auth/google/callback",
        json={"code": "x", "code_verifier": "y", "state": "forged-state"},
    )
    assert resp.status_code == 401


# --- email drift (scenario G, §13.11) -----------------------------------------


@pytest.mark.asyncio
async def test_email_drift_syncs_user_email(
    client: httpx.AsyncClient, test_db, test_admin_user, google_jwks, monkeypatch
):
    await _create_invite(client, "drift@example.com", role="client")
    authz = await _authorize(client)
    sub = "google-sub-drift"
    token = google_jwks["sign"](_claims(authz["nonce"], sub, "drift@example.com"))
    _patch_google(monkeypatch, google_jwks, token)
    assert (await _google_callback(client, authz)).status_code == 200

    # Same sub signs in later with a *new* verified email (free in the system).
    authz2 = await _authorize(client)
    token2 = google_jwks["sign"](_claims(authz2["nonce"], sub, "drift-new@example.com"))
    _patch_google(monkeypatch, google_jwks, token2)
    resp2 = await _google_callback(client, authz2)
    assert resp2.status_code == 200, resp2.text
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {resp2.json()['access_token']}"})
    assert me.json()["email"] == "drift-new@example.com"
    assert me.json()["google_email"] == "drift-new@example.com"

    actions = await _audit_actions(test_db)
    assert "email_changed" in actions


@pytest.mark.asyncio
async def test_email_drift_into_taken_email_rejected(
    client: httpx.AsyncClient, test_db, test_admin_user, google_jwks, monkeypatch
):
    await _create_invite(client, "drift-a@example.com")
    await _create_invite(client, "drift-b@example.com")
    authz = await _authorize(client)
    sub = "google-sub-drift-b"
    token = google_jwks["sign"](_claims(authz["nonce"], sub, "drift-b@example.com"))
    _patch_google(monkeypatch, google_jwks, token)
    assert (await _google_callback(client, authz)).status_code == 200

    # Same sub, but now claiming the OTHER user's (taken) email -> 409 guard.
    authz2 = await _authorize(client)
    token2 = google_jwks["sign"](_claims(authz2["nonce"], sub, "drift-a@example.com"))
    _patch_google(monkeypatch, google_jwks, token2)
    resp2 = await _google_callback(client, authz2)
    assert resp2.status_code == 409
    assert "link_conflict" in await _audit_actions(test_db)


# --- duplicate identity / concurrent first link (§13.3, §13.12) ----------------


@pytest.mark.asyncio
async def test_second_google_identity_on_same_email_conflicts(
    client: httpx.AsyncClient, test_db, test_admin_user, google_jwks, monkeypatch
):
    await _create_invite(client, "one@example.com")
    authz = await _authorize(client)
    token = google_jwks["sign"](_claims(authz["nonce"], "google-sub-one", "one@example.com"))
    _patch_google(monkeypatch, google_jwks, token)
    assert (await _google_callback(client, authz)).status_code == 200

    # A DIFFERENT Google identity claims the same verified email -> reject.
    authz2 = await _authorize(client)
    token2 = google_jwks["sign"](_claims(authz2["nonce"], "google-sub-two", "one@example.com"))
    _patch_google(monkeypatch, google_jwks, token2)
    resp = await _google_callback(client, authz2)
    assert resp.status_code == 409
    assert "link_conflict" in await _audit_actions(test_db)


@pytest.fixture
async def concurrent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Per-request DB session so two callbacks genuinely race on separate connections."""
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
async def test_concurrent_first_time_link_exactly_once(
    concurrent_client: httpx.AsyncClient, test_db, test_admin_user, google_jwks, monkeypatch
):
    """Two simultaneous callbacks for the SAME new Google identity targeting the
    same invite row: exactly ONE account is linked — never two accounts.

    Because the callback resolves `google_sub` first, a second callback that
    runs after the first commits is a clean normal login (200, idempotent
    double-submit), while a genuinely overlapping pair serializes on the unique
    `google_sub` index and the loser 409s. Either way the wrong-case — a second
    ICE account for the same Google identity — is impossible."""
    invite = await _create_invite(concurrent_client, "race@example.com", role="client")
    authz = await _authorize(concurrent_client)
    token = google_jwks["sign"](_claims(authz["nonce"], "google-sub-race", "race@example.com"))
    _patch_google(monkeypatch, google_jwks, token)

    responses = await asyncio.gather(
        _google_callback(concurrent_client, authz, code="c1"),
        _google_callback(concurrent_client, authz, code="c2"),
    )
    codes = sorted(r.status_code for r in responses)
    assert all(c in (200, 409) for c in codes), [r.text for r in responses]
    assert 200 in codes, [r.text for r in responses]

    result = await test_db.execute(
        select(User).where(User.id == uuid.UUID(invite["id"]))
    )
    user = result.scalar_one()
    assert user.google_sub == "google-sub-race"  # bound exactly once

    actions = await _audit_actions(test_db)
    assert actions.count("account_linked") == 1
    assert actions.count("link_conflict") <= 1


# --- deactivation cutoff (§13.6) ----------------------------------------------


@pytest.mark.asyncio
async def test_deactivated_user_callback_and_session_cutoff(
    client: httpx.AsyncClient, test_db, test_admin_user, google_jwks, monkeypatch
):
    await _create_invite(client, "cutoff@example.com")
    authz = await _authorize(client)
    sub = "google-sub-cutoff"
    token = google_jwks["sign"](_claims(authz["nonce"], sub, "cutoff@example.com"))
    _patch_google(monkeypatch, google_jwks, token)
    first = await _google_callback(client, authz)
    assert first.status_code == 200

    header = await auth_header(client, "admin@test.com")
    users = (await client.get("/api/v1/users", headers={"Authorization": header})).json()
    target = next(u for u in users if u["email"] == "cutoff@example.com")
    await client.patch(
        f"/api/v1/users/{target['id']}", headers={"Authorization": header}, json={"is_active": False}
    )

    # Previously-issued Google session is cut off by M9 on the refresh axis.
    assert (await _refresh(client, first.json()["refresh_token"])).status_code == 401

    # A fresh callback for the deactivated identity -> 403, no new session.
    authz2 = await _authorize(client)
    token2 = google_jwks["sign"](_claims(authz2["nonce"], sub, "cutoff@example.com"))
    _patch_google(monkeypatch, google_jwks, token2)
    again = await _google_callback(client, authz2)
    assert again.status_code == 403
    assert again.json()["detail"].lower().startswith("this account has been deactivated")


# --- admin onboarding: validation + audit actions (§13.13, §13.15) ------------


@pytest.mark.asyncio
async def test_google_only_creation_validation(client: httpx.AsyncClient, test_admin_user):
    header = await auth_header(client, "admin@test.com")

    # google_only=true must NOT carry a password.
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={
            "email": "v1@example.com",
            "full_name": "V One",
            "role": "client",
            "google_only": True,
            "password": "SomePass123",
        },
    )
    assert resp.status_code == 422

    # default (password) path unchanged: password still required.
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={"email": "v2@example.com", "full_name": "V Two", "role": "admin"},
    )
    assert resp.status_code == 422

    # invite with no password is valid.
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={
            "email": "v3@example.com",
            "full_name": "V Three",
            "role": "admin",
            "google_only": True,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["has_password"] is False

    # case-insensitive duplicate-guard on invite creation (§5).
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={
            "email": "V3@Example.COM",
            "full_name": "Dupe",
            "role": "client",
            "google_only": True,
        },
    )
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_role_change_and_distinct_activation_audits(
    client: httpx.AsyncClient, test_db, test_admin_user, test_supervisor_user
):
    header = await auth_header(client, "admin@test.com")

    # Role change -> role_changed (not a generic update).
    resp = await client.patch(
        f"/api/v1/users/{test_supervisor_user.id}",
        headers={"Authorization": header},
        json={"role": "procurement_manager"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "procurement_manager"
    assert "role_changed" in await _audit_actions(test_db)

    # full_name only -> generic update.
    await client.patch(
        f"/api/v1/users/{test_supervisor_user.id}",
        headers={"Authorization": header},
        json={"full_name": "Renamed"},
    )
    assert "update" in await _audit_actions(test_db)

    # Deactivate -> user_deactivated (distinct) + M9 session revocation.
    resp = await client.patch(
        f"/api/v1/users/{test_supervisor_user.id}",
        headers={"Authorization": header},
        json={"is_active": False},
    )
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    assert "user_deactivated" in await _audit_actions(test_db)

    login = await client.post(
        "/api/v1/auth/login", json={"email": "supervisor@test.com", "password": "TestPass123"}
    )
    assert login.status_code == 403

    # Reactivate -> user_activated.
    resp = await client.patch(
        f"/api/v1/users/{test_supervisor_user.id}",
        headers={"Authorization": header},
        json={"is_active": True},
    )
    assert resp.status_code == 200 and resp.json()["is_active"] is True
    assert "user_activated" in await _audit_actions(test_db)


# --- regression: password path untouched (§13.9) -------------------------------


@pytest.mark.asyncio
async def test_password_login_still_rejected_for_google_only_invite(
    client: httpx.AsyncClient, test_admin_user
):
    """A pending Google link has no password; password login must fail with the
    same generic 401 (no email enumeration) rather than crash on the NULL hash."""
    await _create_invite(client, "nopass@example.com")
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "nopass@example.com", "password": "Whatever123"}
    )
    assert resp.status_code == 401
    assert "Incorrect email or password" in resp.json()["detail"]
