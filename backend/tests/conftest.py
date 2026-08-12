"""
Pytest configuration and fixtures for backend tests.

Tests run against a real Postgres database, NOT SQLite. Our schema uses
Postgres-native types — ENUM, JSONB, UUID — that SQLite can't faithfully
emulate (an earlier draft of this suite used SQLite and would have failed
to even import). Point TEST_DATABASE_URL at a throwaway database; the
default targets the same Postgres the docker-compose dev stack runs, but a
*separate* database name so running tests never touches real dev/demo data.

The HTTP client fixture uses httpx.AsyncClient + ASGITransport rather than
Starlette's TestClient. TestClient runs the ASGI app in a separate
thread/event loop under the hood, and asyncpg connections are bound to the
loop that created them — mixing the two produces "Future attached to a
different loop" errors as soon as a request touches the database. Using
AsyncClient keeps everything (fixtures + requests) on the single event loop
pytest-asyncio hands to each test.

Before running tests:
    docker compose up -d postgres
    cd backend && pytest tests/ -v

Override the connection (e.g. for CI) with:
    TEST_ADMIN_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/postgres
    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/ice_test_db
"""
import base64
import os
import uuid
from datetime import date
from typing import AsyncGenerator

import pytest

# Settings is a pydantic BaseSettings that reads backend/.env by default.
# That file's Postgres credentials are a local-run template and do NOT
# match the docker-compose Postgres container tests actually run against —
# so set these before `app.main` (and therefore `app.core.config.settings`)
# is imported anywhere. os.environ takes precedence over the .env file.
os.environ.setdefault("POSTGRES_SERVER", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "ice_user")
os.environ.setdefault("POSTGRES_PASSWORD", "ice_pass")
os.environ.setdefault("POSTGRES_DB", "ice_db")
os.environ.setdefault("SECRET_KEY", "test-only-secret-never-use-in-production")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
# M11 Google placeholders so the Google surfaces are enabled (endpoints exist,
# callback tests patch the token exchange + JWKS source). Values never touch a
# real Google client.
os.environ.setdefault("GOOGLE_CLIENT_ID", "ci-test-client.apps.googleusercontent.com")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "ci-test-client-secret")
os.environ.setdefault("GOOGLE_REDIRECT_URI", "http://testserver/google/callback")
os.environ.setdefault("GOOGLE_HOSTED_DOMAIN", "")

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from jose import jwt as jose_jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models.project import Project, ProjectAssignment, ProjectStatus
from app.models.user import User, UserRole

TEST_DB_NAME = "ice_test_db"
ADMIN_DATABASE_URL = os.getenv(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql+asyncpg://ice_user:ice_pass@localhost:5432/postgres",
)
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    f"postgresql+asyncpg://ice_user:ice_pass@localhost:5432/{TEST_DB_NAME}",
)


async def _ensure_test_database_exists() -> None:
    """
    Create the throwaway test database if it doesn't already exist.
    CREATE DATABASE can't run inside a transaction block, hence autocommit.
    Cheap enough (~1ms) to just check on every test_db fixture call, which
    keeps this fixture function-scoped like everything else and avoids
    juggling a separate session-scoped event loop.
    """
    admin_engine = create_async_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
            )
            if exists.scalar_one_or_none() is None:
                await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Could not reach/prepare the test Postgres database. "
            "Run `docker compose up -d postgres` before running tests. "
            f"Original error: {exc}"
        ) from exc
    finally:
        await admin_engine.dispose()


@pytest.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Fresh schema per test: create all tables, yield a session, drop all tables."""
    await _ensure_test_database_exists()

    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)

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
async def client(override_get_db) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Async HTTP client wired directly into the ASGI app (no real socket).

    Rate limiting is disabled by default: slowapi's Limiter keeps its hit
    counts in a process-wide in-memory store, not reset between tests, so
    the suite's many /auth/login calls would otherwise trip the 5/minute
    limit and fail unrelated tests. test_rate_limiting_blocks_after_threshold
    in test_auth.py re-enables it just for that one test.
    """
    app.dependency_overrides[get_db] = override_get_db
    app.state.limiter.enabled = False
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
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
async def test_procurement_user(test_db: AsyncSession) -> User:
    """Create test procurement manager user."""
    user = User(
        email="procurement@test.com",
        full_name="Test Procurement",
        hashed_password=hash_password("TestPass123"),
        role=UserRole.PROCUREMENT_MANAGER,
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


@pytest.fixture
async def test_project(test_db: AsyncSession) -> Project:
    """Create a bare project with no assignments — visible to admin/procurement only."""
    project = Project(
        project_code="PRJ-TEST-0001",
        name="Test Residence",
        site_address="123 Test Street",
        client_name="Test Client Co.",
        status=ProjectStatus.ACTIVE,
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        budget_total=1000000,
    )
    test_db.add(project)
    await test_db.commit()
    await test_db.refresh(project)
    return project


async def assign_user_to_project(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Test helper — grants a supervisor/client access to a project."""
    db.add(ProjectAssignment(project_id=project_id, user_id=user_id))
    await db.commit()


async def auth_header(client: httpx.AsyncClient, email: str, password: str = "TestPass123") -> str:
    """Shared test helper — log in and return a ready-to-use Authorization header value."""
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return f"Bearer {response.json()['access_token']}"


@pytest.fixture
def google_jwks():
    """M11: scratch RSA keypair + a to-mint Google ID tokens signer.

    Tests provide this pair's *public* key as the JWKS cert source and sign
    claims with the private key, so `verify_google_id_token` runs its real
    RS256 signature/iss/aud/exp/nonce verification path with zero network.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    private_pem = (
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
        .decode("utf-8")
    )
    certs = {"test-key-1": public_pem}
    public_numbers = private_key.public_key().public_numbers()

    def _b64_uint(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    jwks = {
        "test-key-1": {
            "kty": "RSA",
            "kid": "test-key-1",
            "alg": "RS256",
            "use": "sig",
            "n": _b64_uint(public_numbers.n),
            "e": _b64_uint(public_numbers.e),
        }
    }

    def sign(claims: dict, kid: str = "test-key-1") -> str:
        return jose_jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": kid})

    return {"certs": certs, "jwks": jwks, "sign": sign, "kid": "test-key-1"}
