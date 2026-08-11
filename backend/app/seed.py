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
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.finance import CostCode, JobCost
from app.models.project import Project, ProjectAssignment, ProjectStatus
from app.models.user import User, UserRole

DEMO_PASSWORD = "DemoPass123"  # Meets requirements: 8+ chars, 1 uppercase, 1 digit


class _DemoUser(TypedDict):
    email: str
    full_name: str
    role: UserRole
    phone: str


DEMO_USERS: list[_DemoUser] = [
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

# Real trade cost codes the demo ledger rows are tagged with, so the Command
# Center budget roll-up (by_cost_code) has believable structure.
_SEED_COST_CODES = [
    CostCode.FOUNDATION,
    CostCode.STRUCTURE,
    CostCode.MASONRY,
    CostCode.ROOFING,
    CostCode.ELECTRICAL,
    CostCode.PLUMBING,
    CostCode.FINISHING,
    CostCode.MATERIAL,
    CostCode.LABOR,
]

_COST_CODE_DESCRIPTIONS = {
    CostCode.FOUNDATION: "Foundation & excavation",
    CostCode.STRUCTURE: "Structural frame",
    CostCode.MASONRY: "Masonry & blockwork",
    CostCode.ROOFING: "Roofing & waterproofing",
    CostCode.ELECTRICAL: "Electrical rough-in",
    CostCode.PLUMBING: "Plumbing rough-in",
    CostCode.FINISHING: "Finishes & fixtures",
    CostCode.MATERIAL: "Materials purchase",
    CostCode.LABOR: "Field labor",
}


def _job_cost_lines(amount: float) -> list[tuple[CostCode, float]]:
    """Split a budget_spent value into a handful of job-cost ledger rows.

    Rows must sum EXACTLY to amount so the M4 invariant
    budget_spent == SUM(job_costs.amount) holds for every seeded project
    (P0 — M3's budget health reads the ledger, not the denormalized column).
    """
    codes = random.sample(_SEED_COST_CODES, k=3)
    first = round(amount * random.uniform(0.3, 0.5), 2)
    second = round(amount * random.uniform(0.2, 0.4), 2)
    third = round(amount - first - second, 2)
    return [(codes[0], first), (codes[1], second), (codes[2], third)]


async def seed(
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    *,
    force: bool = False,
):
    """Load demo users + projects.

    `session_factory` is injectable so tests can run the seed against a
    throwaway database and assert the M4 ledger invariant (P0). `force=True`
    bypasses the ICE_SEED_DEMO gate for the same reason.
    """
    # Demo gating — seed must be explicitly enabled (M10). Prevents the demo
    # dataset from being the implicit permanent project source.
    if not force and os.getenv("ICE_SEED_DEMO", "false").lower() not in ("1", "true", "yes"):
        print(
            "Demo seed skipped: set ICE_SEED_DEMO=true (or pass --demo) to load "
            "demo users and projects. Demo data is intended for development "
            "use only and must not be the permanent project source."
        )
        return

    async with session_factory() as db:
        await _seed(db)

    print("\nDemo login credentials (all use password: {}):".format(DEMO_PASSWORD))
    for u in DEMO_USERS:
        print(f"  {u['role'].value:<22} {u['email']}")


async def _seed(db: AsyncSession) -> None:
    """The actual seed body, bound to an already-open session."""
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
                # M3: health is now computed on read from the ledger + tasks;
                # the manual health columns are deprecated and no longer seeded.
                start_date=start,
                target_end_date=target_end,
                budget_total=budget_total,
                percent_complete=percent_complete,
            )
            db.add(project)
            await db.flush()  # get project.id before creating assignments

            # P0 ledger invariant: every demo project's budget_spent must equal
            # SUM(job_costs.amount). Create matching job-cost rows instead of
            # hand-typing budget_spent, then persist the exact sum.
            incurred = start + timedelta(days=random.randint(1, max((date.today() - start).days, 1)))
            cost_lines = _job_cost_lines(budget_spent)
            for cost_code, amount in cost_lines:
                if amount <= 0:
                    continue
                db.add(
                    JobCost(
                        project_id=project.id,
                        cost_code=cost_code,
                        description=_COST_CODE_DESCRIPTIONS[cost_code],
                        amount=amount,
                        incurred_on=incurred,
                    )
                )
            project.budget_spent = round(sum(amount for _, amount in cost_lines), 2)

            # Assign the demo supervisor to a few sites, and the demo
            # client to their own site, so RBAC-scoped views have data.
            if i < 5:
                db.add(ProjectAssignment(project_id=project.id, user_id=supervisor.id))
            if i == 0:
                db.add(ProjectAssignment(project_id=project.id, user_id=client_user.id))

        await db.commit()
        print(f"Seeded {total} demo projects.")


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
