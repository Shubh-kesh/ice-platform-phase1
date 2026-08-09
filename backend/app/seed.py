"""
Demo data seed script for Phase 1 client demos.

Creates one user per role and 15 realistic residential projects with a mix
of health statuses so the Command Center dashboard has something real to
show. Safe to re-run — skips anything that already exists by email/name.

Usage:
    python -m app.seed
    (or, via Docker: docker compose exec backend python -m app.seed)
"""
import asyncio
import random
from datetime import date, timedelta

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.project import HealthStatus, Project, ProjectAssignment, ProjectStatus
from app.models.user import User, UserRole

DEMO_PASSWORD = "Demo@1234"

DEMO_USERS = [
    {
        "email": "admin@ice.demo",
        "full_name": "Aarav Mehta",
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

            for i in range(15):
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
            print("Seeded 15 demo projects.")

        print("\nDemo login credentials (all use password: {}):".format(DEMO_PASSWORD))
        for u in DEMO_USERS:
            print(f"  {u['role'].value:<22} {u['email']}")


if __name__ == "__main__":
    asyncio.run(seed())
