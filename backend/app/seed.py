"""
Demo data seed script for Phase 1 client demos.

Creates one user per role and 15 realistic residential projects with a mix
of health statuses so the Command Center dashboard has something real to
show. Safe to re-run — skips anything that already exists by email/name.

DEMO-GATED (Phase 3 M10): this script intentionally refuses to run unless
explicitly enabled, so demo data never becomes the permanent source of
projects in a real deployment. Enable with:

    ICE_SEED_DEMO=true python -m app.seed

Usage:
    ICE_SEED_DEMO=true python -m app.seed
    (or, via Docker: docker compose exec backend python -m app.seed)
"""
import asyncio
import os
import random
from datetime import date, timedelta

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.project import HealthStatus, Project, ProjectAssignment, ProjectStatus
from app.models.user import User, UserRole

DEMO_PASSWORD = "DemoPass123"  # Meets requirements: 8+ chars, 1 uppercase, 1 digit

DEMO_USERS = [
    {
        "email": "Pankaj1234@gmail.com",
        "full_name": "Pankaj Sen",
        "role": UserRole.ADMIN,
        "phone": "9876500001",
    },
    {
        "email": "supervisor@ice.demo",
        "full_name": "Rohan Deshmukh",
        "role": UserRole.SITE_SUPERVISOR,
        "phone": "9876500002",
    },
    {
        "email": "procurement@ice.demo",
        "full_name": "Priya Nair",
        "role": UserRole.PROCUREMENT_MANAGER,
        "phone": "9876500003",
    },
    {
        "email": "client@ice.demo",
        "full_name": "Sanjay Kulkarni",
        "role": UserRole.CLIENT,
        "phone": "9876500004",
    },
]

CITIES = [
    ("Jabalpur, Madhya Pradesh", "Vijay Nagar"),
    ("Bhopal, Madhya Pradesh", "Kolar Road"),
    ("Indore, Madhya Pradesh", "Vijay Nagar"),
    ("Nagpur, Maharashtra", "Wardha Road"),
    ("Pune, Maharashtra", "Baner"),
    ("Mumbai, Maharashtra", "Andheri East"),
    ("Raipur, Chhattisgarh", "Shankar Nagar"),
    ("Lucknow, Uttar Pradesh", "Gomti Nagar"),
    ("Jaipur, Rajasthan", "Vaishali Nagar"),
    ("Ahmedabad, Gujarat", "Bopal"),
    ("Surat, Gujarat", "Vesu"),
    ("Bengaluru, Karnataka", "Whitefield"),
    ("Hyderabad, Telangana", "Gachibowli"),
    ("Nashik, Maharashtra", "Gangapur Road"),
    ("Bhilai, Chhattisgarh", "Sector 6"),
]

CLIENT_NAMES = [
    "Mr. Anil Pathak", "Mr. Baljindar Singh", "Mr. Santosh Gupta",
    "Ratnesh Sen", "Suneeta Singh", "Mr. Vikram Rathore",
    "Mrs. Kavita Joshi", "Mr. Deepak Agarwal", "Mrs. Meena Iyer",
    "Mr. Farhan Sheikh", "Mr. Ramesh Chandran", "Mrs. Anjali Bose",
    "Mr. Harpreet Sandhu", "Mr. Manoj Tiwari", "Mrs. Sunita Reddy",
]

HEALTH_MIX = (
    [HealthStatus.GREEN] * 8 + [HealthStatus.AMBER] * 5 + [HealthStatus.RED] * 2
)


def random_health() -> HealthStatus:
    return random.choice(HEALTH_MIX)


async def seed():
    # Demo gating — seed must be explicitly enabled (M10). Prevents the demo
    # dataset from being the implicit permanent project source.
    if os.getenv("ICE_SEED_DEMO", "false").lower() not in ("1", "true", "yes"):
        print(
            "Demo seed skipped: set ICE_SEED_DEMO=true (or pass --demo) to load "
            "demo users and projects. Demo data is intended for development "
            "use only and must not be the permanent project source."
        )
        return

    async with AsyncSessionLocal() as db:
        # --- Users ---
        created_users: dict[UserRole, User] = {}
        for u in DEMO_USERS:
            result = await db.execute(select(User).where(User.email == u["email"]))
            existing = result.scalar_one_or_none()
            if existing:
                created_users[u["role"]] = existing
                continue
            user = User(
                email=u["email"],
                hashed_password=hash_password(DEMO_PASSWORD),
                full_name=u["full_name"],
                phone=u["phone"],
                role=u["role"],
                is_active=True,
            )
            db.add(user)
            created_users[u["role"]] = user

        await db.commit()
        for user in created_users.values():
            await db.refresh(user)

        # --- Projects ---
        result = await db.execute(select(Project))
        existing_count = len(result.scalars().all())
        if existing_count >= 15:
            print(f"Already have {existing_count} projects — skipping project seed.")
        else:
            supervisor = created_users[UserRole.SITE_SUPERVISOR]
            client_user = created_users[UserRole.CLIENT]

            # Distinct project codes so the demo set does not collide with
            # any admin-created projects (unique project_code, M10).
            year = str(date.today().year)
            max_seq = await _max_demo_seq(db, year)
            total = min(15, 15 - existing_count)

            for i in range(total):
                city, locality = CITIES[i]
                client_name = CLIENT_NAMES[i]
                budget_total = random.choice([3500000, 4800000, 6200000, 8500000, 12000000])
                percent_complete = random.choice([15, 30, 45, 55, 65, 75, 90, 100])
                budget_spent = round(budget_total * (percent_complete / 100) * random.uniform(0.85, 1.15), 2)
                status = (
                    ProjectStatus.COMPLETED
                    if percent_complete == 100
                    else ProjectStatus.ACTIVE
                    if percent_complete > 0
                    else ProjectStatus.PLANNING
                )
                start = date.today() - timedelta(days=random.randint(30, 400))
                target_end = start + timedelta(days=random.randint(180, 540))

                project = Project(
                    project_code=f"PRJ-{year}-{max_seq + i + 1:04d}",
                    name=f"{client_name.split()[-1]} Residence, {city.split(',')[0]}",
                    site_address=f"{locality}, {city}",
                    client_name=client_name,
                    status=status,
                    timeline_health=random_health(),
                    budget_health=random_health(),
                    safety_health=random_health(),
                    start_date=start,
                    target_end_date=target_end,
                    budget_total=budget_total,
                    budget_spent=budget_spent,
                    percent_complete=percent_complete,
                )
                db.add(project)
                await db.flush()  # get project.id before creating assignments

                # Assign the demo supervisor to a few sites, and the demo
                # client to their own site, so RBAC-scoped views have data.
                if i < 5:
                    db.add(ProjectAssignment(project_id=project.id, user_id=supervisor.id))
                if i == 0:
                    db.add(ProjectAssignment(project_id=project.id, user_id=client_user.id))

            await db.commit()
            print(f"Seeded {total} demo projects.")

        print("\nDemo login credentials (all use password: {}):".format(DEMO_PASSWORD))
        for u in DEMO_USERS:
            print(f"  {u['role'].value:<22} {u['email']}")


async def _max_demo_seq(db, year: str) -> int:
    """Highest PRJ-YYYY-#### sequence currently present (for unique codes)."""
    result = await db.execute(
        select(Project.project_code)
        .where(Project.project_code.like(f"PRJ-{year}-%"))
        .order_by(Project.project_code.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    if last is None:
        return 0
    return int(last.rsplit("-", 1)[1])


if __name__ == "__main__":
    asyncio.run(seed())
