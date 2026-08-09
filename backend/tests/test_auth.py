"""
Tests for authentication endpoints.
"""
import pytest
from fastapi.testclient import TestClient

from app.models.user import User, UserRole
from app.core.security import hash_password


@pytest.mark.asyncio
async def test_login_success(client: TestClient, test_db, test_admin_user: User):
    """Test successful login."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "TestPass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_password(client: TestClient, test_admin_user: User):
    """Test login with invalid password."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "WrongPassword123"},
    )
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: TestClient):
    """Test login with nonexistent user."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@test.com", "password": "TestPass123"},
    )
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_inactive_user(client: TestClient, test_db):
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

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@test.com", "password": "TestPass123"},
    )
    assert response.status_code == 403
    assert "deactivated" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user(client: TestClient, test_admin_user: User):
    """Test getting current user info."""
    # First login to get token
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "TestPass123"},
    )
    access_token = login_response.json()["access_token"]

    # Then get current user
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    user = response.json()
    assert user["email"] == "admin@test.com"
    assert user["full_name"] == "Test Admin"
    assert user["role"] == "admin"


@pytest.mark.asyncio
async def test_get_current_user_without_token(client: TestClient):
    """Test getting current user without token."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 403  # FastAPI returns 403 for missing credentials


@pytest.mark.asyncio
async def test_refresh_token(client: TestClient, test_admin_user: User):
    """Test token refresh."""
    # Login to get tokens
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "TestPass123"},
    )
    refresh_token = login_response.json()["refresh_token"]

    # Refresh the token
    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: TestClient):
    """Test refresh with invalid token."""
    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid-token"},
    )
    assert response.status_code == 401
    assert "Invalid refresh token" in response.json()["detail"]
