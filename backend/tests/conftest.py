"""
Pytest configuration and fixtures for backend tests.

Provides database session, test client, authenticated user, and other fixtures.
"""
import asyncio
import pytest
from typing import AsyncGenerator

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models.user import User, UserRole


# Test database setup
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Create test database and yield session."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
def override_get_db(test_db):
    """Override get_db dependency for tests."""
    async def _get_db():
        yield test_db

    return _get_db


@pytest.fixture
def client(override_get_db):
    """Create test client with overridden dependencies."""
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
async def test_admin_user(test_db: AsyncSession) -> User:
    """Create test admin user."""
    user = User(
        email="admin@test.com",
        full_name="Test Admin",
        hashed_password=hash_password("TestPass123"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest.fixture
async def test_supervisor_user(test_db: AsyncSession) -> User:
    """Create test site supervisor user."""
    user = User(
        email="supervisor@test.com",
        full_name="Test Supervisor",
        hashed_password=hash_password("TestPass123"),
        role=UserRole.SITE_SUPERVISOR,
        is_active=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest.fixture
async def test_client_user(test_db: AsyncSession) -> User:
    """Create test client user."""
    user = User(
        email="client@test.com",
        full_name="Test Client",
        hashed_password=hash_password("TestPass123"),
        role=UserRole.CLIENT,
        is_active=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user
