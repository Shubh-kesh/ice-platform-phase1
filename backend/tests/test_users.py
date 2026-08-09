"""
Tests for user management endpoints and RBAC.
"""
import httpx
import pytest

from app.models.user import User
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_list_users_admin(client: httpx.AsyncClient, test_admin_user: User):
    """Test admin can list users."""
    header = await auth_header(client, "admin@test.com")
    response = await client.get("/api/v1/users", headers={"Authorization": header})
    assert response.status_code == 200
    users = response.json()
    assert isinstance(users, list)
    assert len(users) >= 1  # At least the admin user


@pytest.mark.asyncio
async def test_list_users_non_admin(client: httpx.AsyncClient, test_supervisor_user: User):
    """Test non-admin cannot list users."""
    header = await auth_header(client, "supervisor@test.com")
    response = await client.get("/api/v1/users", headers={"Authorization": header})
    assert response.status_code == 403
    assert "not permitted" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_user_admin(client: httpx.AsyncClient, test_admin_user: User):
    """Test admin can create user."""
    header = await auth_header(client, "admin@test.com")
    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
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
async def test_create_user_non_admin(client: httpx.AsyncClient, test_supervisor_user: User):
    """Test non-admin cannot create user."""
    header = await auth_header(client, "supervisor@test.com")
    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={
            "email": "newuser@test.com",
            "full_name": "New User",
            "role": "site_supervisor",
            "password": "NewPass123",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_user_weak_password(client: httpx.AsyncClient, test_admin_user: User):
    """Test password policy enforcement."""
    header = await auth_header(client, "admin@test.com")

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={"email": "test@test.com", "full_name": "Test", "role": "admin", "password": "Pass1"},
    )
    assert response.status_code == 422
    assert "8 characters" in str(response.json())

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={"email": "test@test.com", "full_name": "Test", "role": "admin", "password": "password123"},
    )
    assert response.status_code == 422
    assert "uppercase" in str(response.json())

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={"email": "test@test.com", "full_name": "Test", "role": "admin", "password": "PasswordOnly"},
    )
    assert response.status_code == 422
    assert "digit" in str(response.json())


@pytest.mark.asyncio
async def test_create_duplicate_user(client: httpx.AsyncClient, test_admin_user: User):
    """Test cannot create user with duplicate email."""
    header = await auth_header(client, "admin@test.com")

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": header},
        json={
            "email": "admin@test.com",
            "full_name": "Another Admin",
            "role": "admin",
            "password": "NewPass123",
        },
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_user_admin(client: httpx.AsyncClient, test_admin_user: User, test_supervisor_user: User):
    """Test admin can update user."""
    header = await auth_header(client, "admin@test.com")
    response = await client.patch(
        f"/api/v1/users/{test_supervisor_user.id}",
        headers={"Authorization": header},
        json={"full_name": "Updated Name"},
    )
    assert response.status_code == 200
    user = response.json()
    assert user["full_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_deactivate_user(client: httpx.AsyncClient, test_admin_user: User, test_supervisor_user: User):
    """Test admin can deactivate user."""
    header = await auth_header(client, "admin@test.com")
    response = await client.patch(
        f"/api/v1/users/{test_supervisor_user.id}",
        headers={"Authorization": header},
        json={"is_active": False},
    )
    assert response.status_code == 200
    user = response.json()
    assert user["is_active"] is False

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "supervisor@test.com", "password": "TestPass123"},
    )
    assert login_response.status_code == 403
