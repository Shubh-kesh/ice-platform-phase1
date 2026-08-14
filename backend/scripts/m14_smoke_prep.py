"""Prep the M14 smoke DB: fresh schema + the four role users + one ACTIVE project.
Run before starting uvicorn for the smoke test. Destroys ice_test_db contents."""
import asyncio
import os
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.core.security import hash_password
from app.models.project import Project, ProjectStatus
from app.models.user import User, UserRole
from tests.conftest import TEST_DATABASE_URL

USERS = [
    ("admin@test.com", "Smoke Admin", UserRole.ADMIN),
    ("procurement@test.com", "Smoke Procurement", UserRole.PROCUREMENT_MANAGER),
    ("supervisor@test.com", "Smoke Supervisor", UserRole.SITE_SUPERVISOR),
    ("client@test.com", "Smoke Client", UserRole.CLIENT),
]


async def main() -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with S() as db:
        for email, name, role in USERS:
            db.add(
                User(
                    email=email,
                    full_name=name,
                    hashed_password=hash_password("TestPass123"),
                    role=role,
                    is_active=True,
                )
            )
        db.add(
            Project(
                project_code="PRJ-2026-9001",
                name="Smoke Residence",
                site_address="1 Smoke Rd",
                client_name="Smoke Co",
                status=ProjectStatus.ACTIVE,
                start_date=date(2026, 1, 1),
                target_end_date=date(2026, 12, 31),
                budget_total=1000000,
            )
        )
        await db.commit()
    await engine.dispose()
    print("smoke DB ready")


if __name__ == "__main__":
    asyncio.run(main())
