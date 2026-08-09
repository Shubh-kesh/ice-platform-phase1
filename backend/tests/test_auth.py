"""
Tests for authentication endpoints.
"""
import httpx
import pytest

from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_login_success(client: httpx.AsyncClient, test_db, test_admin_user: User):
    """Test successful login."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "TestPass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_password(client: httpx.AsyncClient, test_admin_user: User):
    """Test login with invalid password."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "WrongPassword123"},
    )
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: httpx.AsyncClient):
    """Test login with nonexistent user."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@test.com", "password": "TestPass123"},
    )
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_inactive_user(client: httpx.AsyncClient, test_db):
    """Test login with inactive user."""
    from app.models.user import User
    from app.core.security import hash_password

    user = User(
        email="inactive@test.com",
        full_name="Inactive User",
        hashed_password=hash_password("TestPass123"),
        role=UserRole.ADMIN,
        is_active=False,
    )
    test_db.add(user)
    await test_db.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@test.com", "password": "TestPass123"},
    )
    assert response.status_code == 403
    assert "deactivated" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user(client: httpx.AsyncClient, test_admin_user: User):
    """Test getting current user info."""
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "TestPass123"},
    )
    access_token = login_response.json()["access_token"]

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    user = response.json()
    assert user["email"] == "admin@test.com"
    assert user["full_name"] == "Test Admin"
    assert user["role"] == "admin"


@pytest.mark.asyncio
async def test_get_current_user_without_token(client: httpx.AsyncClient):
    """Test getting current user without token."""
    response = await client.get("/api/v1/auth/me")
    # OAuth2PasswordBearer (auto_error=True) rejects a missing Authorization
    # header itself, before get_current_user's own 401 logic even runs.
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client: httpx.AsyncClient, test_admin_user: User):
    """Test token refresh."""
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "TestPass123"},
    )
    refresh_token = login_response.json()["refresh_token"]

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: httpx.AsyncClient):
    """Test refresh with invalid token."""
    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid-token"},
    )
    assert response.status_code == 401
    assert "Invalid refresh token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limiting_blocks_after_threshold(client: httpx.AsyncClient, test_admin_user: User):
    """
    The `client` fixture disables rate limiting by default (see conftest.py)
    so the rest of the suite isn't affected by slowapi's process-wide hit
    counter. Re-enable it just for this test to verify the limit is real.
    """
    from app.main import app

    app.state.limiter.enabled = True
    try:
        responses = [
            await client.post(
                "/api/v1/auth/login",
                json={"email": "admin@test.com", "password": "WrongPassword"},
            )
            for _ in range(6)
        ]
    finally:
        app.state.limiter.enabled = False

    # First 5 attempts are rejected on credentials (401); the 6th is
    # rejected by the rate limiter itself (429) before credentials are
    # even checked.
    assert [r.status_code for r in responses[:5]] == [401] * 5
    assert responses[5].status_code == 429
