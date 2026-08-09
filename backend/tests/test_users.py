"""
Tests for user management endpoints and RBAC.
"""
import pytest
from fastapi.testclient import TestClient

from app.models.user import User, UserRole


def _get_auth_header(client: TestClient, email: str, password: str = "TestPass123") -> str:
    """Helper to get auth token."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return f"Bearer {response.json()['access_token']}"


@pytest.mark.asyncio
async def test_list_users_admin(client: TestClient, test_admin_user: User):
    """Test admin can list users."""
    auth_header = _get_auth_header(client, "admin@test.com")
    response = client.get(
        "/api/v1/users",
        headers={"Authorization": auth_header},
    )
    assert response.status_code == 200
    users = response.json()
    assert isinstance(users, list)
    assert len(users) >= 1  # At least the admin user


@pytest.mark.asyncio
async def test_list_users_non_admin(client: TestClient, test_supervisor_user: User):
    """Test non-admin cannot list users."""
    auth_header = _get_auth_header(client, "supervisor@test.com")
    response = client.get(
        "/api/v1/users",
        headers={"Authorization": auth_header},
    )
    assert response.status_code == 403
    assert "not permitted" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_user_admin(client: TestClient, test_admin_user: User):
    """Test admin can create user."""
    auth_header = _get_auth_header(client, "admin@test.com")
    response = client.post(
        "/api/v1/users",
        headers={"Authorization": auth_header},
        json={
            "email": "newuser@test.com",
            "full_name": "New User",
            "phone": "1234567890",
            "role": "site_supervisor",
            "password": "NewPass123",
        },
    )
    assert response.status_code == 201
    user = response.json()
    assert user["email"] == "newuser@test.com"
    assert user["role"] == "site_supervisor"


@pytest.mark.asyncio
async def test_create_user_non_admin(client: TestClient, test_supervisor_user: User):
    """Test non-admin cannot create user."""
    auth_header = _get_auth_header(client, "supervisor@test.com")
    response = client.post(
        "/api/v1/users",
        headers={"Authorization": auth_header},
        json={
            "email": "newuser@test.com",
            "full_name": "New User",
            "role": "site_supervisor",
            "password": "NewPass123",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_user_weak_password(client: TestClient, test_admin_user: User):
    """Test password policy enforcement."""
    auth_header = _get_auth_header(client, "admin@test.com")

    # Test too short
    response = client.post(
        "/api/v1/users",
        headers={"Authorization": auth_header},
        json={
            "email": "test@test.com",
            "full_name": "Test",
            "role": "admin",
            "password": "Pass1",  # Only 5 chars
        },
    )
    assert response.status_code == 422
    assert "8 characters" in str(response.json())

    # Test missing uppercase
    response = client.post(
        "/api/v1/users",
        headers={"Authorization": auth_header},
        json={
            "email": "test@test.com",
            "full_name": "Test",
            "role": "admin",
            "password": "password123",  # No uppercase
        },
    )
    assert response.status_code == 422
    assert "uppercase" in str(response.json())

    # Test missing digit
    response = client.post(
        "/api/v1/users",
        headers={"Authorization": auth_header},
        json={
            "email": "test@test.com",
            "full_name": "Test",
            "role": "admin",
            "password": "PasswordOnly",  # No digit
        },
    )
    assert response.status_code == 422
    assert "digit" in str(response.json())


@pytest.mark.asyncio
async def test_create_duplicate_user(client: TestClient, test_admin_user: User):
    """Test cannot create user with duplicate email."""
    auth_header = _get_auth_header(client, "admin@test.com")

    # Try to create user with existing email
    response = client.post(
        "/api/v1/users",
        headers={"Authorization": auth_header},
        json={
            "email": "admin@test.com",  # Already exists
            "full_name": "Another Admin",
            "role": "admin",
            "password": "NewPass123",
        },
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_user_admin(client: TestClient, test_admin_user: User, test_supervisor_user: User):
    """Test admin can update user."""
    auth_header = _get_auth_header(client, "admin@test.com")
    response = client.patch(
        f"/api/v1/users/{test_supervisor_user.id}",
        headers={"Authorization": auth_header},
        json={"full_name": "Updated Name"},
    )
    assert response.status_code == 200
    user = response.json()
    assert user["full_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_deactivate_user(client: TestClient, test_admin_user: User, test_supervisor_user: User):
    """Test admin can deactivate user."""
    auth_header = _get_auth_header(client, "admin@test.com")
    response = client.patch(
        f"/api/v1/users/{test_supervisor_user.id}",
        headers={"Authorization": auth_header},
        json={"is_active": False},
    )
    assert response.status_code == 200
    user = response.json()
    assert user["is_active"] is False

    # Try to login as deactivated user
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "supervisor@test.com", "password": "TestPass123"},
    )
    assert login_response.status_code == 403
