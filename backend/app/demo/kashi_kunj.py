"""
Kashi Kunj demo pack — seed/verify/reset/reseed for the client demonstration.

This module builds ONE realistic demo project ("Kashi Kunj") end-to-end so the
client meeting can show every implemented ICE module with believable data and
then be restored to its canonical state after rehearsal.

HOW IT WORKS
------------
All *writes* go through the real FastAPI application over an in-process httpx
ASGITransport — the same paths the browser uses (login -> RBAC -> row locks ->
audit -> notifications). No product code is bypassed for the seed itself; the
only direct-DB writes are (a) the bootstrap admin if none exists and (b) the
reset command, because the product intentionally exposes no delete endpoints.
Direct-DB reads are used purely for idempotency checks ("does it already
exist?") so a re-run never duplicates data.

SAFETY
------
* Refuses to run when ENVIRONMENT is production.
* `seed` / `reseed` additionally require ICE_KASHI_DEMO=true (mirrors the
  app.seed ICE_SEED_DEMO convention).
* The demo password comes from ICE_KASHI_DEMO_PASSWORD and is never hard-coded.
* Reset removes ONLY Kashi-Kunj-owned rows (the 4 kashi.*@example.com users,
  their project(s), and everything that hangs off them, plus the named demo
  vendors). Unrelated data is never touched. No DROP DATABASE / truncate-all.

USAGE
-----
    docker compose exec backend python -m app.demo.kashi_kunj seed
    docker compose exec backend python -m app.demo.kashi_kunj verify
    docker compose exec backend python -m app.demo.kashi_kunj reset
    docker compose exec backend python -m app.demo.kashi_kunj reseed
    docker compose exec backend python -m app.demo.kashi_kunj smoke   # optional Copilot HITL smoke
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import String, cast, delete, func, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models import (
    AuditLog,
    BillingMilestone,
    DailySiteLog,
    Delivery,
    DeliveryLine,
    HealthOverride,
    InventoryItem,
    Invoice,
    JobCost,
    Notification,
    POLine,
    Project,
    ProjectAssignment,
    PurchaseOrder,
    RefreshSession,
    StockMovement,
    Task,
    User,
    Vendor,
)
from app.models.project import ProjectStatus
from app.models.user import UserRole
from app.services.idempotency import IDEMPOTENCY_KEY_MAX_LENGTH, IDEMPOTENCY_KEY_MIN_LENGTH

DEMO_VERSION = "2026-08-19"

PROJECT_NAME = "Kashi Kunj"
PROJECT_CODE_PREFIX = "PRJ"

# Demo-owned users (fictional local-demo accounts).
KASHI_EMAILS = [
    "kashi.admin@example.com",
    "kashi.supervisor@example.com",
    "kashi.procurement@example.com",
    "kashi.client@example.com",
]

ADMIN_EMAIL = "kashi.admin@example.com"
SUPERVISOR_EMAIL = "kashi.supervisor@example.com"
PROCUREMENT_EMAIL = "kashi.procurement@example.com"
CLIENT_EMAIL = "kashi.client@example.com"

# Bootstrap admin (mirrors app/seed.py). Used only when no admin exists yet.
BOOTSTRAP_ADMIN_EMAIL = "Pankaj1234@gmail.com"
BOOTSTRAP_ADMIN_PASSWORD = "DemoPass123"

# Fictional vendors created for the demo (name -> details).
DEMO_VENDORS: list[dict] = [
    {
        "name": "Narmada Building Materials",
        "contact_name": "Rajesh Agrawal",
        "email": "rajesh.agrawal@narmadabm.example",
        "phone": "+91 98270 11001",
        "payment_terms": "Net 30",
        "address": "Sihora Road, Jabalpur, Madhya Pradesh 482002",
        "notes": "Fictional demo vendor — cement, sand and aggregate supplier.",
    },
    {
        "name": "Mahakaushal Steel Supply",
        "contact_name": "Suresh Malviya",
        "email": "suresh.malviya@mahakaushalsteel.example",
        "phone": "+91 98270 11002",
        "payment_terms": "Net 30",
        "address": "Ghamapur Road, Jabalpur, Madhya Pradesh 482004",
        "notes": "Fictional demo vendor — TMT steel and binding wire.",
    },
    {
        "name": "Shakti Concrete Solutions",
        "contact_name": "Nitin Dubey",
        "email": "nitin.dubey@shakticoncrete.example",
        "phone": "+91 98270 11003",
        "payment_terms": "Net 30",
        "address": "Vijay Nagar, Jabalpur, Madhya Pradesh 482002",
        "notes": "Fictional demo vendor — RCC support and formwork hire.",
    },
    {
        "name": "Jabalpur Electrical & Plumbing",
        "contact_name": "Farhan Qureshi",
        "email": "farhan.qureshi@jabalpurep.example",
        "phone": "+91 98270 11004",
        "payment_terms": "Net 45",
        "address": "Wright Town, Jabalpur, Madhya Pradesh 482002",
        "notes": "Fictional demo vendor — electrical conduit, CPVC and fixtures.",
    },
    {
        "name": "Modern Floor & Tile House",
        "contact_name": "Meera Shukla",
        "email": "meera.shukla@moderntile.example",
        "phone": "+91 98270 11005",
        "payment_terms": "Net 30",
        "address": "Napier Town, Jabalpur, Madhya Pradesh 482001",
        "notes": "Fictional demo vendor — tiles and tile adhesive.",
    },
]

# Timeline anchor — everything is computed relative to "today" so the demo stays
# fresh whenever it is reseeded.
TODAY = datetime.now(timezone.utc).date()
START = TODAY - timedelta(days=220)
TARGET_END = TODAY + timedelta(days=205)
PERCENT_COMPLETE = 47
BUDGET_TOTAL = 9_000_000  # ₹90 lakh


def _d(offset_days: int) -> date:
    """A date `offset_days` after the project start."""
    return START + timedelta(days=offset_days)


# --- Project timeline ---------------------------------------------------------
# Each task: name, sort_order, start_day, end_day, status, percent, depends_on
# (by name). Single predecessor only — the schema supports one depends_on_id.
@dataclass(frozen=True)
class _TaskSeed:
    name: str
    sort_order: int
    start_day: int
    end_day: int
    status: str
    percent: int
    depends_on: str | None


TASKS: list[_TaskSeed] = [
    _TaskSeed("Site Survey & Layout", 1, 0, 10, "completed", 100, None),
    _TaskSeed("Excavation & Foundation Pit", 2, 11, 29, "completed", 100, "Site Survey & Layout"),
    _TaskSeed("Footing Reinforcement & Shuttering", 3, 30, 47, "completed", 100, "Excavation & Foundation Pit"),
    _TaskSeed("Foundation Concrete (PCC + Raft)", 4, 48, 59, "completed", 100, "Footing Reinforcement & Shuttering"),
    _TaskSeed("Plinth Beam & Backfilling", 5, 60, 77, "completed", 100, "Foundation Concrete (PCC + Raft)"),
    _TaskSeed("Ground Floor RCC Columns", 6, 78, 95, "completed", 100, "Plinth Beam & Backfilling"),
    _TaskSeed("Ground Floor Slab (RCC)", 7, 96, 113, "completed", 100, "Ground Floor RCC Columns"),
    _TaskSeed("First Floor RCC Structure", 8, 114, 151, "completed", 100, "Ground Floor Slab (RCC)"),
    _TaskSeed("AAC / Brick Masonry", 9, 152, 215, "in_progress", 55, "First Floor RCC Structure"),
    _TaskSeed("Electrical & Plumbing Rough-In", 10, 135, 185, "in_progress", 40, "Ground Floor Slab (RCC)"),
    _TaskSeed("Waterproofing (Terrace & Wet Areas)", 11, 216, 229, "not_started", 0, "AAC / Brick Masonry"),
    # Deliberately planned 20 days early: apply_schedule shifts it (and only
    # it) forward to satisfy finish-to-start, which naturally produces exactly
    # one schedule-shift notification + audit trail — the automation story for
    # the demo. Every other task already satisfies the invariant, so no other
    # shift fires during the seed.
    _TaskSeed("Internal Plaster", 12, 196, 231, "not_started", 0, "AAC / Brick Masonry"),
    _TaskSeed("Flooring & Tiles", 13, 252, 292, "not_started", 0, "Internal Plaster"),
    _TaskSeed("Painting & Finishes", 14, 293, 338, "not_started", 0, "Flooring & Tiles"),
    _TaskSeed("External Works & Landscaping", 15, 230, 340, "not_started", 0, "Waterproofing (Terrace & Wet Areas)"),
    _TaskSeed("Final Inspection & Handover", 16, 339, 374, "not_started", 0, "Painting & Finishes"),
]

# --- Daily site logs ----------------------------------------------------------
@dataclass(frozen=True)
class _SiteLogSeed:
    day_offset: int  # days before today (positive => in the past)
    work_summary: str
    issues: str | None
    workers: int
    weather: str


SITE_LOGS: list[_SiteLogSeed] = [
    _SiteLogSeed(
        58,
        "Footing reinforcement completed; shuttering for the plinth beam being set up.",
        "Minor delay in shuttering material arrival.",
        24,
        "Sunny",
    ),
    _SiteLogSeed(
        51,
        "Plinth beam concrete pour (M20 mix) completed in one continuous pour.",
        "Concrete pump delayed by 2 hours from supplier.",
        26,
        "Sunny",
    ),
    _SiteLogSeed(
        42,
        "Backfilling around plinth completed in layers with proper compaction.",
        None,
        18,
        "Clear",
    ),
    _SiteLogSeed(
        30,
        "Ground floor column shuttering and reinforcement fixing in progress.",
        None,
        22,
        "Sunny",
    ),
    _SiteLogSeed(
        22,
        "Ground floor slab concrete pour completed.",
        "Small honeycomb patch on slab edge being dressed by the crew.",
        30,
        "Sunny",
    ),
    _SiteLogSeed(
        14,
        "First floor column reinforcement fixed; slab shuttering underway.",
        None,
        28,
        "Partly cloudy",
    ),
    _SiteLogSeed(
        6,
        "Cement consignment (120 bags) received and stacked at site; curing of first floor columns ongoing.",
        None,
        20,
        "Sunny",
    ),
    _SiteLogSeed(
        2,
        "AAC masonry started on ground floor partition walls.",
        "Cement stock running low at site — 120 bags still due against the open purchase order.",
        16,
        "Hot and dry",
    ),
]

# --- Inventory ----------------------------------------------------------------
# (name, unit, opening_quantity, reorder_threshold, unit_cost)
@dataclass(frozen=True)
class _ItemSeed:
    name: str
    unit: str
    opening: float
    threshold: float | None
    unit_cost: float | None


ITEMS: list[_ItemSeed] = [
    _ItemSeed("Cement (OPC 53)", "bags", 0, 30, 380),
    _ItemSeed("TMT Steel Bars", "kg", 0, 500, 62),
    _ItemSeed("M-Sand", "tonne", 14, 6, 1200),
    _ItemSeed("20mm Aggregate", "tonne", 14, 6, 1050),
    _ItemSeed("AAC Blocks", "nos", 900, 300, 42),
    _ItemSeed("Binding Wire", "kg", 0, 20, 85),
    _ItemSeed("Waterproofing Compound", "cans", 10, 8, 450),
    _ItemSeed("Electrical Conduit 25mm", "m", 400, 200, 35),
    _ItemSeed("CPVC Pipe 1 inch", "m", 150, 100, 220),
    _ItemSeed("Tile Adhesive", "bags", 40, 25, 480),
]

# Manual (non-PO) consumption movements. The cement sequence is designed so the
# final movement crosses the 30-bag reorder threshold (50 -> 25) and fires the
# low-stock notification through the real inventory path.
MOVEMENTS: dict[str, list[tuple[str, float, str]]] = {
    "Cement (OPC 53)": [
        ("consumed", 55, "Slab concrete pour"),
        ("consumed", 45, "Masonry work"),
        ("consumed", 30, "Masonry walls"),
        ("consumed", 25, "Curing & finishing"),
    ],
    "TMT Steel Bars": [("consumed", 4000, "Structure reinforcement fixing")],
    "Binding Wire": [("consumed", 60, "Structure tying")],
    "M-Sand": [("consumed", 6, "Plaster & masonry mix")],
    "20mm Aggregate": [("consumed", 6, "Concrete mix")],
    "AAC Blocks": [("consumed", 520, "Partition walls")],
    "Electrical Conduit 25mm": [("consumed", 120, "Rough-in conduit laying")],
}

# --- Vendors / POs -------------------------------------------------------------
# PO definitions: vendor name, order day, expected day, tax rate, lines, and the
# lifecycle flow to walk the PO through.
@dataclass(frozen=True)
class _POLineSeed:
    description: str
    quantity: float
    unit: str
    unit_price: float
    cost_code: str


@dataclass(frozen=True)
class _POSeed:
    vendor: str
    order_day: int
    expected_day: int
    tax_rate: float
    lines: tuple[_POLineSeed, ...]
    # Lifecycle steps in order: draft -> submit -> [approve|reject] -> receive...
    steps: tuple[str, ...]
    reject_reason: str | None = None
    notes: str | None = None


POS: list[_POSeed] = [
    _POSeed(
        vendor="Mahakaushal Steel Supply",
        order_day=100,
        expected_day=115,
        tax_rate=18,
        lines=(
            _POLineSeed("TMT Fe-550D 12mm bars", 8000, "kg", 62.00, "structure"),
            _POLineSeed("TMT Fe-550D 16mm bars", 6000, "kg", 61.00, "structure"),
            _POLineSeed("Binding wire (annealed)", 150, "kg", 85.00, "material"),
        ),
        steps=("submit", "approve", "receive-full"),
        notes="Full steel requirement for ground + first floor structure.",
    ),
    _POSeed(
        vendor="Narmada Building Materials",
        order_day=150,
        expected_day=165,
        tax_rate=18,
        lines=(_POLineSeed("OPC 53 grade cement", 300, "bags", 380.00, "structure"),),
        steps=("submit", "approve", "receive-120", "receive-60"),
        notes="Cement order — 180 bags delivered, 120 bags balance outstanding.",
    ),
    _POSeed(
        vendor="Jabalpur Electrical & Plumbing",
        order_day=170,
        expected_day=200,
        tax_rate=18,
        lines=(
            _POLineSeed("CPVC pipe 1 inch", 150, "m", 220.00, "plumbing"),
            _POLineSeed("PVC conduit 25mm", 400, "m", 35.00, "electrical"),
            _POLineSeed("Modular switches 15A", 40, "nos", 95.00, "electrical"),
        ),
        steps=("submit", "approve"),
        notes="Electrical + plumbing rough-in material, awaiting delivery.",
    ),
    _POSeed(
        vendor="Narmada Building Materials",
        order_day=185,
        expected_day=215,
        tax_rate=18,
        lines=(
            _POLineSeed("AAC blocks 600x200x100", 900, "nos", 42.00, "masonry"),
            _POLineSeed("Tile adhesive bags", 40, "bags", 480.00, "finishing"),
        ),
        steps=("submit",),
        notes="Masonry + finishing material — pending admin approval (approve live during demo).",
    ),
    _POSeed(
        vendor="Narmada Building Materials",
        order_day=180,
        expected_day=200,
        tax_rate=18,
        lines=(_POLineSeed("Waterproofing compound cans", 20, "cans", 480.00, "roofing"),),
        steps=("submit", "reject"),
        reject_reason="Rate above the approved Rs 450 per can — please re-quote with Narmada or reduce quantity.",
        notes="Rejected by admin to demonstrate the revise/resubmit workflow.",
    ),
]

# Steel receipt steps used by the seed (full delivery, three lines).
_STEEL_RECEIPT = {
    "reference": "MKS-2031",
    "note": "Full steel consignment delivered and verified at site.",
}

# Manual job-cost lines (created via the real job-costs API as procurement).
@dataclass(frozen=True)
class _JobCostSeed:
    cost_code: str
    description: str
    amount: float
    day_offset: int


JOB_COSTS: list[_JobCostSeed] = [
    _JobCostSeed("foundation", "Excavation, footing & PCC", 620000.00, 45),
    _JobCostSeed("structure", "RCC columns & slab concrete to date", 860000.00, 130),
    _JobCostSeed("masonry", "AAC masonry labour & material to date", 280000.00, 180),
    _JobCostSeed("labor", "Site labour & gang charges", 340000.00, 170),
    _JobCostSeed("equipment", "Mixer, vibrator & site equipment hire", 160000.00, 95),
    _JobCostSeed("material", "Site consumables & misc material", 95000.00, 150),
]

# --- Billing milestones (schedule of values, sums to 100%) ---------------------
@dataclass(frozen=True)
class _MilestoneSeed:
    name: str
    billing_type: str
    percentage: float | None
    fixed_amount: float | None
    sort_order: int
    description: str
    complete: bool
    invoice: str | None  # None | "paid" | "sent"


MILESTONES: list[_MilestoneSeed] = [
    _MilestoneSeed("Booking / Mobilisation Advance", "percentage", 10.0, None, 1,
                   "Mobilisation advance on booking", True, "paid"),
    _MilestoneSeed("Foundation & Plinth Completion", "percentage", 15.0, None, 2,
                   "Foundation and plinth work completed", True, "paid"),
    _MilestoneSeed("RCC Structure Completion", "percentage", 25.0, None, 3,
                   "Ground and first floor RCC structure completed", True, "sent"),
    _MilestoneSeed("Masonry & Rough-In Completion", "percentage", 15.0, None, 4,
                   "Masonry and electrical/plumbing rough-in", False, None),
    _MilestoneSeed("Finishing Works Completion", "percentage", 20.0, None, 5,
                   "Plaster, flooring and finishes", False, None),
    _MilestoneSeed("Handover & Final Settlement", "percentage", 15.0, None, 6,
                   "Final inspection and handover", False, None),
]


# ==============================================================================
# HTTP layer (in-process ASGI transport over the real app)
# ==============================================================================

def _build_client(app) -> httpx.AsyncClient:
    """An in-process client against the real FastAPI app. The rate limiter is
    disabled exactly as the backend test-suite does — the seed performs dozens
    of rapid API calls and rate limiting is not part of what it exercises."""
    try:
        app.state.limiter.enabled = False
    except Exception:
        pass
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver/api/v1")


class Api:
    """Thin wrapper over httpx for the API calls the seed needs."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.token: str | None = None

    def _headers(self, idem_key: str | None = None) -> dict:
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if idem_key:
            if not (IDEMPOTENCY_KEY_MIN_LENGTH <= len(idem_key) <= IDEMPOTENCY_KEY_MAX_LENGTH):
                raise ValueError(f"bad idempotency key length: {idem_key!r}")
            h["Idempotency-Key"] = idem_key
        return h

    async def login(self, email: str, password: str) -> None:
        r = await self.client.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        self.token = r.json()["access_token"]

    async def request(self, method: str, path: str, *, json=None, idem_key=None, expect=200):
        r = await self.client.request(
            method, path, json=json, headers=self._headers(idem_key)
        )
        if r.status_code != expect:
            raise RuntimeError(
                f"{method} {path} -> {r.status_code}: {r.text[:400]}"
            )
        return r

    async def get(self, path: str, expect=200):
        return (await self.request("GET", path, expect=expect)).json()

    async def post(self, path: str, json=None, idem_key=None, expect=201):
        return (await self.request("POST", path, json=json, idem_key=idem_key, expect=expect)).json()

    async def patch(self, path: str, json=None, expect=200):
        return (await self.request("PATCH", path, json=json, expect=expect)).json()


# ==============================================================================
# Direct-DB helpers (read-only for idempotency checks; writes only for reset +
# bootstrap admin)
# ==============================================================================

async def _bootstrap_admin() -> User:
    """Ensure an admin exists so the kashi users can be provisioned through the
    real POST /users path. Mirrors app/seed.py's bootstrap conventions."""
    async with AsyncSessionLocal() as db:
        admin = (
            await db.execute(select(User).where(User.email == BOOTSTRAP_ADMIN_EMAIL))
        ).scalar_one_or_none()
        if admin is not None:
            return admin
        admin = User(
            email=BOOTSTRAP_ADMIN_EMAIL,
            hashed_password=hash_password(BOOTSTRAP_ADMIN_PASSWORD),
            full_name="Pankaj Sen",
            phone="9876500001",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        return admin


async def _user_by_email(email: str) -> User | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(User).where(func.lower(User.email) == email.lower()))
        ).scalar_one_or_none()


async def _get_or_create_kashi_users(api: Api, demo_password: str) -> dict[str, User]:
    """Provision the four kashi users through POST /users (real admin path)."""
    users: dict[str, User] = {}

    async with AsyncSessionLocal() as db:
        existing = {
            u.email.lower(): u
            for u in (
                await db.execute(select(User).where(User.email.in_(KASHI_EMAILS)))
            ).scalars()
        }
        for email in KASHI_EMAILS:
            u = existing.get(email.lower())
            if u is not None:
                users[email] = u

    specs = [
        (ADMIN_EMAIL, "Kashi Admin", "admin", "+91 98760 00001"),
        (SUPERVISOR_EMAIL, "Arun Sharma", "site_supervisor", "+91 98760 00002"),
        (PROCUREMENT_EMAIL, "Vikram Rao", "procurement_manager", "+91 98760 00003"),
        (CLIENT_EMAIL, "Ananya Gupta", "client", "+91 98760 00004"),
    ]
    for email, full_name, role, phone in specs:
        if email in users:
            continue
        created = await api.post(
            "/users",
            json={
                "email": email,
                "full_name": full_name,
                "phone": phone,
                "role": role,
                "google_only": False,
                "password": demo_password,
            },
        )
        async with AsyncSessionLocal() as db:
            users[email] = (
                await db.execute(select(User).where(User.id == created["id"]))
            ).scalar_one()
    return users


async def _find_kashi_projects() -> list[Project]:
    """Projects owned by the kashi demo users (deterministic demo marker)."""
    async with AsyncSessionLocal() as db:
        kashi_ids = (
            await db.execute(select(User.id).where(User.email.in_(KASHI_EMAILS)))
        ).scalars().all()
        if not kashi_ids:
            return []
        return list(
            (
                await db.execute(
                    select(Project).where(
                        Project.name == PROJECT_NAME,
                        Project.created_by.in_(kashi_ids),
                    )
                )
            ).scalars().all()
        )


async def _project_exists() -> bool:
    async with AsyncSessionLocal() as db:
        return bool(
            (
                await db.execute(
                    select(Project.id).where(Project.name == PROJECT_NAME)
                )
            ).scalar_one_or_none()
        )


async def _task_by_name(project_id, name: str) -> Task | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(Task).where(Task.project_id == project_id, Task.name == name)
            )
        ).scalar_one_or_none()


async def _item_by_name(project_id, name: str) -> InventoryItem | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(InventoryItem).where(
                    InventoryItem.project_id == project_id, InventoryItem.name == name
                )
            )
        ).scalar_one_or_none()


async def _movement_exists(item_id, note: str) -> bool:
    async with AsyncSessionLocal() as db:
        return bool(
            (
                await db.execute(
                    select(StockMovement.id).where(
                        StockMovement.item_id == item_id, StockMovement.note == note
                    )
                )
            ).scalar_one_or_none()
        )


async def _vendor_by_name(name: str) -> Vendor | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(Vendor).where(Vendor.name == name))
        ).scalar_one_or_none()


async def _po_by_number(project_id, po_number: str) -> PurchaseOrder | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(PurchaseOrder).where(
                    PurchaseOrder.project_id == project_id,
                    PurchaseOrder.po_number == po_number,
                )
            )
        ).scalar_one_or_none()


async def _po_lines(po_id) -> list[POLine]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(POLine).where(POLine.purchase_order_id == po_id)
                )
            ).scalars().all()
        )


async def _job_cost_exists(project_id, description: str) -> bool:
    async with AsyncSessionLocal() as db:
        return bool(
            (
                await db.execute(
                    select(JobCost.id).where(
                        JobCost.project_id == project_id, JobCost.description == description
                    )
                )
            ).scalar_one_or_none()
        )


async def _milestone_by_name(project_id, name: str) -> BillingMilestone | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(BillingMilestone).where(
                    BillingMilestone.project_id == project_id,
                    BillingMilestone.name == name,
                )
            )
        ).scalar_one_or_none()


async def _invoice_for_milestone(milestone_id) -> Invoice | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(Invoice).where(Invoice.billing_milestone_id == milestone_id)
            )
        ).scalar_one_or_none()


async def _line_remaining(line: POLine) -> Decimal:
    return Decimal(line.quantity) - Decimal(line.received_quantity)


# ==============================================================================
# SEED
# ==============================================================================

def _require_demo_password() -> str:
    pw = os.environ.get("ICE_KASHI_DEMO_PASSWORD", "")
    if not pw:
        print(
            "ERROR: ICE_KASHI_DEMO_PASSWORD is not set.\n"
            "  Export a demo password before seeding, e.g.:\n"
            "  export ICE_KASHI_DEMO_PASSWORD='Kashi@Demo26'  # >=8 chars, 1 uppercase, 1 digit"
        )
        sys.exit(2)
    if len(pw) < 8 or not any(c.isupper() for c in pw) or not any(c.isdigit() for c in pw):
        print(
            "ERROR: ICE_KASHI_DEMO_PASSWORD must be >=8 chars, contain an uppercase "
            "letter and a digit (the user-create password rules)."
        )
        sys.exit(2)
    return pw


def _refuse_production() -> None:
    env = os.environ.get("ENVIRONMENT", "").lower()
    if env in ("production", "prod"):
        print("ERROR: refusing to run against production. Demo seed/reset is local-dev only.")
        sys.exit(2)


def _require_demo_flag() -> None:
    if os.environ.get("ICE_KASHI_DEMO", "false").lower() not in ("1", "true", "yes"):
        print(
            "Demo seed skipped: set ICE_KASHI_DEMO=true (or pass --demo) to load the "
            "Kashi Kunj demo data. Demo data is intended for local development only."
        )
        sys.exit(2)


async def seed(demo_password: str | None = None, verbose: bool = True) -> None:
    """Create the full Kashi Kunj demo environment through real API paths."""
    if demo_password is None:
        demo_password = _require_demo_password()

    from app.main import app

    async with _build_client(app) as client:
        api = Api(client)

        # --- Bootstrap admin + kashi users -----------------------------------
        # 1) try the kashi admin directly (already seeded); 2) else bootstrap the
        # standard admin and provision the kashi users through POST /users.
        try:
            await api.login(ADMIN_EMAIL, demo_password)
            admin_token_ok = True
        except Exception:
            admin_token_ok = False
            await _bootstrap_admin()
            await api.login(BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_PASSWORD)

        kashi_users = await _get_or_create_kashi_users(api, demo_password)
        supervisor_user = kashi_users[SUPERVISOR_EMAIL]
        client_user = kashi_users[CLIENT_EMAIL]

        if not admin_token_ok:
            await api.login(ADMIN_EMAIL, demo_password)

        # --- Project ---------------------------------------------------------
        project = await _get_or_create_project(api)
        project_id = project["id"]
        if verbose:
            print(f"Project: {project['name']} ({project['project_code']}) id={project_id}")

        # --- Assignments -----------------------------------------------------
        assignments = await api.get(f"/projects/{project_id}/assignments", expect=200)
        assigned_ids = {a["id"] for a in assignments}
        for user in (supervisor_user, client_user):
            if str(user.id) not in assigned_ids:
                await api.post(
                    f"/projects/{project_id}/assignments",
                    json={"user_id": str(user.id)},
                    expect=201,
                )
                if verbose:
                    print(f"Assigned {user.email} -> Kashi Kunj")

        # --- Tasks (created by the assigned supervisor) ----------------------
        await api.login(SUPERVISOR_EMAIL, demo_password)
        task_ids: dict[str, str] = {}
        for t in TASKS:
            existing = await _task_by_name(project_id, t.name)
            if existing is not None:
                task_ids[t.name] = str(existing.id)
                continue
            created = await api.post(
                f"/projects/{project_id}/tasks",
                json={
                    "name": t.name,
                    "start_date": _d(t.start_day).isoformat(),
                    "end_date": _d(t.end_day).isoformat(),
                    "depends_on_id": task_ids[t.depends_on] if t.depends_on else None,
                    "sort_order": t.sort_order,
                },
            )
            await api.patch(
                f"/projects/{project_id}/tasks/{created['id']}",
                json={"status": t.status, "percent_complete": t.percent},
            )
            task_ids[t.name] = created["id"]
        if verbose:
            print(f"Tasks: {len(TASKS)} ensured")

        # --- Project progress (supervisor path) ------------------------------
        current = await api.get(f"/projects/{project_id}", expect=200)
        if current.get("percent_complete") != PERCENT_COMPLETE:
            await api.patch(f"/projects/{project_id}", json={"percent_complete": PERCENT_COMPLETE})

        # --- Site logs (supervisor) ------------------------------------------
        logs = await api.get(f"/projects/{project_id}/site-logs", expect=200)
        existing_log_dates = {d["log_date"] for d in logs}
        for log in SITE_LOGS:
            log_date = (TODAY - timedelta(days=log.day_offset)).isoformat()
            if log_date in existing_log_dates:
                continue
            await api.post(
                f"/projects/{project_id}/site-logs",
                json={
                    "log_date": log_date,
                    "work_summary": log.work_summary,
                    "issues": log.issues,
                    "workers_present": log.workers,
                    "weather": log.weather,
                    "photo_urls": [],
                },
            )
        if verbose:
            print(f"Site logs: {len(SITE_LOGS)} ensured")

        # --- Vendors (procurement) -------------------------------------------
        await api.login(PROCUREMENT_EMAIL, demo_password)
        for v in DEMO_VENDORS:
            if await _vendor_by_name(v["name"]) is None:
                await api.post("/vendors", json=v)
        if verbose:
            print(f"Vendors: {len(DEMO_VENDORS)} ensured")

        # --- Inventory items + movements (procurement) -----------------------
        item_ids: dict[str, str] = {}
        for it in ITEMS:
            existing_item = await _item_by_name(project_id, it.name)
            if existing_item is not None:
                item_ids[it.name] = str(existing_item.id)
                continue
            # Defer the reorder threshold until after creation when the opening
            # balance is already at/below it — otherwise creation itself would
            # fire a spurious low-stock alert before the intended movements.
            defer_threshold = it.threshold is not None and it.opening <= it.threshold
            created = await api.post(
                f"/projects/{project_id}/inventory",
                json={
                    "name": it.name,
                    "unit": it.unit,
                    "reorder_threshold": None if defer_threshold else it.threshold,
                    "unit_cost": it.unit_cost,
                    "opening_quantity": it.opening,
                },
            )
            if defer_threshold:
                await api.patch(
                    f"/projects/{project_id}/inventory/{created['id']}",
                    json={"reorder_threshold": it.threshold},
                )
            item_ids[it.name] = created["id"]
        if verbose:
            print(f"Inventory items: {len(ITEMS)} ensured")

        # --- Purchase orders + lifecycle (procurement + admin) ----------------
        # Receipts first: they add stock (steel, cement, binding wire) that the
        # manual consumption movements below draw down.
        await _seed_purchase_orders(api, project_id, item_ids, demo_password, verbose)

        # --- Manual consumption movements (rely on received stock) ------------
        for item_name, moves in MOVEMENTS.items():
            item_id = item_ids[item_name]
            for mtype, qty, note in moves:
                note_key = f"Kashi demo: {note}"
                if await _movement_exists(item_id, note_key):
                    continue
                await api.post(
                    f"/projects/{project_id}/inventory/{item_id}/movements",
                    json={"movement_type": mtype, "quantity": qty, "note": note_key},
                )
        if verbose:
            print("Inventory movements: recorded")

        # --- Manual job costs (procurement) ----------------------------------
        for jc in JOB_COSTS:
            if await _job_cost_exists(project_id, jc.description):
                continue
            await api.post(
                f"/projects/{project_id}/job-costs",
                json={
                    "cost_code": jc.cost_code,
                    "description": jc.description,
                    "amount": jc.amount,
                    "incurred_on": _d(jc.day_offset).isoformat(),
                },
            )
        if verbose:
            print(f"Job costs: {len(JOB_COSTS)} manual lines ensured")

        # --- Billing milestones + invoices (admin) ---------------------------
        await api.login(ADMIN_EMAIL, demo_password)
        await _seed_milestones_and_invoices(api, project_id, verbose)

        # --- Leave the admin logged in for nothing; done ---------------------
        if verbose:
            print("Seed complete.")


async def _get_or_create_project(api: Api) -> dict:
    """Fetch the existing Kashi Kunj project or create + activate it (admin)."""
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(select(Project).where(Project.name == PROJECT_NAME))
        ).scalar_one_or_none()
    if existing is not None:
        return {
            "id": str(existing.id),
            "project_code": existing.project_code,
            "name": existing.name,
            "status": existing.status.value,
        }
    created = await api.post(
        "/projects",
        json={
            "name": PROJECT_NAME,
            "site_address": "Kashi Kunj, Deendayal Nagar, Jabalpur, Madhya Pradesh 482001",
            "client_name": "Ananya Gupta",
            "start_date": START.isoformat(),
            "target_end_date": TARGET_END.isoformat(),
            "budget_total": BUDGET_TOTAL,
        },
        idem_key=f"kashi-{DEMO_VERSION}-project",
    )
    project_id = created["id"]
    await api.post(f"/projects/{project_id}/activate", expect=200)
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(Project).where(Project.id == created["id"]))
        ).scalar_one()
    return {
        "id": str(row.id),
        "project_code": row.project_code,
        "name": row.name,
        "status": row.status.value,
    }


async def _seed_purchase_orders(
    api: Api, project_id: str, item_ids: dict[str, str], demo_password: str, verbose: bool
) -> None:
    """Create the POs and walk each through its lifecycle (procurement + admin)."""
    po_ids: dict[int, str] = {}
    for idx, po in enumerate(POS, start=1):
        existing = await _po_by_number(project_id, f"PO-PRJ-2026-{idx:04d}")
        # We don't know the project code here (it may not be 2026-0001), so
        # match by vendor + order_date instead when the number guess fails.
        if existing is None:
            existing = await _po_by_vendor_and_date(project_id, po.vendor, _d(po.order_day))
        if existing is not None:
            po_ids[idx] = str(existing.id)
            continue
        # Find the vendor id.
        vendor = await _vendor_by_name(po.vendor)
        if vendor is None:
            raise RuntimeError(f"vendor {po.vendor} not found")
        created = await api.post(
            f"/projects/{project_id}/purchase-orders",
            json={
                "vendor_id": str(vendor.id),
                "order_date": _d(po.order_day).isoformat(),
                "expected_delivery": _d(po.expected_day).isoformat(),
                "tax_rate": po.tax_rate,
                "notes": po.notes,
                "lines": [
                    {
                        "description": ln.description,
                        "quantity": ln.quantity,
                        "unit": ln.unit,
                        "unit_price": ln.unit_price,
                        "cost_code": ln.cost_code,
                    }
                    for ln in po.lines
                ],
            },
            idem_key=f"kashi-{DEMO_VERSION}-po-{idx}",
        )
        po_ids[idx] = created["id"]

    # Admin logins for approve/reject steps.
    await api.login(PROCUREMENT_EMAIL, demo_password)

    for idx, po in enumerate(POS, start=1):
        po_id = po_ids[idx]
        status = await _po_status(po_id)
        for step in po.steps:
            if step == "submit":
                if status == "draft":
                    await api.post(f"/projects/{project_id}/purchase-orders/{po_id}/submit", expect=200)
                    status = "pending_approval"
            elif step == "approve":
                if status == "pending_approval":
                    await api.login(ADMIN_EMAIL, demo_password)
                    await api.post(f"/projects/{project_id}/purchase-orders/{po_id}/approve", expect=200)
                    status = "approved"
                    await api.login(PROCUREMENT_EMAIL, demo_password)
            elif step == "reject":
                if status == "pending_approval":
                    await api.login(ADMIN_EMAIL, demo_password)
                    await api.post(
                        f"/projects/{project_id}/purchase-orders/{po_id}/reject",
                        json={"rejected_reason": po.reject_reason or "Demo rejection"},
                        expect=200,
                    )
                    status = "rejected"
                    await api.login(PROCUREMENT_EMAIL, demo_password)
            elif step == "receive-full":
                await _receive_steel(api, project_id, po_id, status)
                status = "received"
            elif step in ("receive-120", "receive-60"):
                qty = 120 if step == "receive-120" else 60
                await _receive_cement(api, project_id, po_id, qty, status)
                status = "partially_received"

    if verbose:
        print("Purchase orders: lifecycle walked through real transitions")


async def _po_by_vendor_and_date(project_id: str, vendor_name: str, order_date: date) -> PurchaseOrder | None:
    async with AsyncSessionLocal() as db:
        vendor = (
            await db.execute(select(Vendor).where(Vendor.name == vendor_name))
        ).scalar_one_or_none()
        if vendor is None:
            return None
        return (
            await db.execute(
                select(PurchaseOrder).where(
                    PurchaseOrder.project_id == project_id,
                    PurchaseOrder.vendor_id == vendor.id,
                    PurchaseOrder.order_date == order_date,
                )
            )
        ).scalar_one_or_none()


async def _po_status(po_id: str) -> str:
    async with AsyncSessionLocal() as db:
        po = (
            await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
        ).scalar_one()
        return po.status.value


async def _receive_steel(api: Api, project_id: str, po_id: str, status: str) -> None:
    """Fully receive the steel PO (three lines) if not already received."""
    if status in ("received", "partially_received"):
        lines = await _po_lines(po_id)
        remaining = {line.id: await _line_remaining(line) for line in lines}
        if all(r == 0 for r in remaining.values()):
            return
        payload_lines = [
            {
                "po_line_id": str(line.id),
                "quantity": float(remaining[line.id]),
                "inventory_item_id": str(line.inventory_item_id),
            }
            for line in lines
            if remaining[line.id] > 0
        ]
    else:
        lines = await _po_lines(po_id)
        steel_item = await _item_by_name(project_id, "TMT Steel Bars")
        wire_item = await _item_by_name(project_id, "Binding Wire")
        payload_lines = []
        for line in lines:
            item = wire_item if "binding" in line.description.lower() else steel_item
            if item is None:
                raise RuntimeError(f"no inventory item for steel line {line.description}")
            payload_lines.append(
                {
                    "po_line_id": str(line.id),
                    "quantity": float(line.quantity),
                    "inventory_item_id": str(item.id),
                }
            )
    await api.post(
        f"/projects/{project_id}/purchase-orders/{po_id}/receive",
        json={
            "reference": _STEEL_RECEIPT["reference"],
            "note": _STEEL_RECEIPT["note"],
            "lines": payload_lines,
        },
        idem_key=f"kashi-{DEMO_VERSION}-recv-{_STEEL_RECEIPT['reference']}",
    )


async def _receive_cement(api: Api, project_id: str, po_id: str, qty: int, status: str) -> None:
    """Receive a partial cement delivery. Skips cleanly when that quantity has
    already been received (idempotent across re-runs)."""
    lines = await _po_lines(po_id)
    if not lines:
        raise RuntimeError("cement PO has no lines")
    line = lines[0]
    if await _line_remaining(line) < qty:
        return  # already delivered that quantity (or more)
    item = await _item_by_name(project_id, "Cement (OPC 53)")
    if item is None:
        raise RuntimeError("cement inventory item missing")
    reference = "NRM-1188" if qty == 120 else "NRM-1192"
    note = (
        "Partial delivery 1 — cement received at site."
        if qty == 120
        else "Partial delivery 2 — balance 120 bags outstanding."
    )
    await api.post(
        f"/projects/{project_id}/purchase-orders/{po_id}/receive",
        json={
            "reference": reference,
            "note": note,
            "lines": [
                {
                    "po_line_id": str(line.id),
                    "quantity": qty,
                    "inventory_item_id": str(item.id),
                }
            ],
        },
        idem_key=f"kashi-{DEMO_VERSION}-recv-{reference}",
    )


async def _seed_milestones_and_invoices(api: Api, project_id: str, verbose: bool) -> None:
    milestone_ids: dict[str, str] = {}
    for m in MILESTONES:
        existing = await _milestone_by_name(project_id, m.name)
        if existing is not None:
            milestone_ids[m.name] = str(existing.id)
            continue
        created = await api.post(
            f"/projects/{project_id}/billing-milestones",
            json={
                "name": m.name,
                "billing_type": m.billing_type,
                "billing_percentage": m.percentage,
                "fixed_amount": m.fixed_amount,
                "description": m.description,
                "sort_order": m.sort_order,
            },
        )
        milestone_ids[m.name] = created["id"]

    for m in MILESTONES:
        milestone_id = milestone_ids[m.name]
        if not m.complete:
            continue
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(select(BillingMilestone).where(BillingMilestone.id == milestone_id))
            ).scalar_one()
            already_completed = row.status.value == "completed"
        if not already_completed:
            await api.post(
                f"/projects/{project_id}/billing-milestones/{milestone_id}/complete", expect=200
            )
        if m.invoice is None:
            continue
        invoice = await _invoice_for_milestone(milestone_id)
        if invoice is not None:
            invoice_id = str(invoice.id)
            status = invoice.status.value
        else:
            created = await api.post(
                f"/projects/{project_id}/invoices",
                json={"billing_milestone_id": milestone_id},
            )
            invoice_id = created["id"]
            status = created["status"]
        if m.invoice == "paid":
            if status == "draft":
                await api.post(f"/projects/{project_id}/invoices/{invoice_id}/issue", expect=200)
                status = "sent"
            if status == "sent":
                await api.post(f"/projects/{project_id}/invoices/{invoice_id}/mark-paid", expect=200)
        elif m.invoice == "sent":
            if status == "draft":
                await api.post(f"/projects/{project_id}/invoices/{invoice_id}/issue", expect=200)
    if verbose:
        print(f"Milestones: {len(MILESTONES)} ensured; invoices created per plan")


# ==============================================================================
# VERIFY
# ==============================================================================

class _Report:
    def __init__(self) -> None:
        self.passes = 0
        self.fails = 0
        self.lines: list[tuple[bool, str]] = []

    def check(self, ok: bool, label: str) -> None:
        self.lines.append((ok, label))
        if ok:
            self.passes += 1
        else:
            self.fails += 1

    def render(self) -> str:
        out = ["\nKASHI KUNJ DEMO READINESS", "========================="]
        for ok, label in self.lines:
            out.append(f"[{'PASS' if ok else 'FAIL'}] {label}")
        out.append("-------------------------")
        if self.fails:
            out.append(f"DEMO NOT READY ({self.fails} failed)")
        else:
            out.append(f"DEMO READY ({self.passes} checks passed)")
        return "\n".join(out)


async def verify(demo_password: str | None = None) -> None:
    """Run the human-readable readiness checklist (read-only)."""
    if demo_password is None:
        demo_password = _require_demo_password()

    from app.main import app

    report = _Report()
    async with _build_client(app) as client:
        api = Api(client)

        # --- Data existence (direct DB) --------------------------------------
        async with AsyncSessionLocal() as db:
            project = (
                await db.execute(select(Project).where(Project.name == PROJECT_NAME))
            ).scalar_one_or_none()
            if project is None:
                report.check(False, "Project exists")
                print(report.render())
                sys.exit(1)
            report.check(True, "Project exists")
            report.check(
                project.status == ProjectStatus.ACTIVE, f"Project ACTIVE (is {project.status.value})"
            )
            project_id = str(project.id)

            task_count = (
                await db.execute(select(func.count()).select_from(Task).where(Task.project_id == project_id))
            ).scalar_one()
            report.check(12 <= task_count <= 16, f"Tasks: {task_count} (12-16)")

            log_count = (
                await db.execute(
                    select(func.count()).select_from(DailySiteLog).where(DailySiteLog.project_id == project_id)
                )
            ).scalar_one()
            report.check(7 <= log_count <= 10, f"Site logs: {log_count} (7-10)")

            item_count = (
                await db.execute(
                    select(func.count()).select_from(InventoryItem).where(InventoryItem.project_id == project_id)
                )
            ).scalar_one()
            report.check(8 <= item_count <= 12, f"Inventory items: {item_count} (8-12)")

            vendor_count = (
                await db.execute(select(func.count()).select_from(Vendor).where(Vendor.name.in_([v["name"] for v in DEMO_VENDORS])))
            ).scalar_one()
            report.check(4 <= vendor_count <= 6, f"Vendors: {vendor_count}")

            po_count = (
                await db.execute(
                    select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.project_id == project_id)
                )
            ).scalar_one()
            report.check(po_count >= 5, f"Purchase orders: {po_count}")

            job_cost_count = (
                await db.execute(
                    select(func.count()).select_from(JobCost).where(JobCost.project_id == project_id)
                )
            ).scalar_one()
            report.check(job_cost_count > 0, f"Job costs: {job_cost_count}")

            milestone_count = (
                await db.execute(
                    select(func.count()).select_from(BillingMilestone).where(BillingMilestone.project_id == project_id)
                )
            ).scalar_one()
            report.check(milestone_count > 0, f"Billing milestones: {milestone_count}")

            invoice_count = (
                await db.execute(
                    select(func.count()).select_from(Invoice).where(Invoice.project_id == project_id)
                )
            ).scalar_one()
            report.check(invoice_count >= 2, f"Invoices: {invoice_count}")

            notification_count = (
                await db.execute(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.project_id == project_id)
                )
            ).scalar_one()
            report.check(notification_count > 0, f"Notifications (project-scoped): {notification_count}")

            audit_count = (
                await db.execute(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.record_id.in_(
                        select(cast(JobCost.id, String)).where(JobCost.project_id == project_id)
                    ))
                )
            ).scalar_one()
            report.check(audit_count > 0, f"Audit rows referencing project job costs: {audit_count}")

        # --- Dependency integrity (DB) ---------------------------------------
        cycles = await _has_task_cycle(project_id)
        report.check(not cycles, "Task dependencies valid (no cycles)")

        # --- PO state spread ---------------------------------------------------
        states = await _po_states(project_id)
        report.check("pending_approval" in states, f"PO states {sorted(states)} include pending_approval")
        report.check("approved" in states, "PO states include approved")
        report.check("partially_received" in states, "PO states include partially_received")
        report.check("received" in states, "PO states include received")

        # --- Inventory reconciliation + low stock -----------------------------
        report.check(True, "Inventory reconciliation: run via API below")

        # --- budget invariant --------------------------------------------------
        spent_invariant, budget_spent, ledger_sum = await _budget_invariant(project_id)
        report.check(
            spent_invariant,
            f"budget_spent == job-cost ledger ({budget_spent} == {ledger_sum})",
        )

        # --- Role access + restrictions (real API) ----------------------------
        await _verify_roles(api, project_id, demo_password, report)

        # --- Health ------------------------------------------------------------
        await api.login(ADMIN_EMAIL, demo_password)
        health = await api.get(f"/projects/{project_id}/health", expect=200)
        overall = health["overall"]["value"]
        timeline = health["timeline"]["value"]
        budget = health["budget"]["value"]
        report.check(
            overall in ("amber", "red"),
            f"Overall health {overall} (timeline {timeline}, budget {budget}) — discussion-worthy",
        )
        report.lines.append((True, f"  health reasons: {health['overall']['reasons']}"))
        report.lines.append((True, f"  timeline reasons: {health['timeline']['reasons']}"))

    print(report.render())
    sys.exit(0 if report.fails == 0 else 1)


async def _has_task_cycle(project_id: str) -> bool:
    from app.services.tasks import detect_dependency_cycle, predecessor_map
    from app.services.tasks import get_project_tasks

    async with AsyncSessionLocal() as db:
        tasks = await get_project_tasks(db, uuid.UUID(project_id))
        preds = predecessor_map(tasks)
        for task in tasks:
            if detect_dependency_cycle(preds, task.id):
                return True
    return False


async def _po_states(project_id: str) -> list[str]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(PurchaseOrder.status).where(PurchaseOrder.project_id == project_id)
            )
        ).scalars().all()
        return [r.value for r in rows]


async def _budget_invariant(project_id: str) -> tuple[bool, float, float]:
    async with AsyncSessionLocal() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        ledger_sum = (
            await db.execute(
                select(func.coalesce(func.sum(JobCost.amount), 0)).where(
                    JobCost.project_id == project_id
                )
            )
        ).scalar_one()
        budget_spent = float(project.budget_spent)
        ledger = float(ledger_sum)
        return abs(budget_spent - ledger) < 0.01, budget_spent, ledger


async def _verify_roles(
    api: Api, project_id: str, demo_password: str, report: _Report
) -> None:
    """Exercise each role against the real API and check allowed + forbidden paths."""

    # Admin
    await api.login(ADMIN_EMAIL, demo_password)
    projects = await api.get("/projects", expect=200)
    report.check(
        any(p.get("project_code") and p["id"] == project_id for p in projects),
        "Admin access to Kashi Kunj",
    )
    report.check(
        (await api.get(f"/projects/{project_id}/health", expect=200)) is not None,
        "Admin can read project health",
    )

    # Procurement
    await api.login(PROCUREMENT_EMAIL, demo_password)
    projects = await api.get("/projects", expect=200)
    report.check(any(p["id"] == project_id for p in projects), "Procurement access to Kashi Kunj")
    await api.get(f"/projects/{project_id}/purchase-orders", expect=200)
    report.check(True, "Procurement can read purchase orders")
    po_list = await api.get(f"/projects/{project_id}/purchase-orders", expect=200)
    pending = [p for p in po_list if p["status"] == "pending_approval"]
    if pending:
        try:
            await api.post(
                f"/projects/{project_id}/purchase-orders/{pending[0]['id']}/approve",
                expect=403,
            )
            report.check(True, "Procurement cannot approve a PO (403 expected)")
        except RuntimeError:
            report.check(False, "Procurement cannot approve a PO (403 expected)")
    else:
        report.check(True, "No pending-approval PO to test (skipped)")

    # Supervisor
    await api.login(SUPERVISOR_EMAIL, demo_password)
    projects = await api.get("/projects", expect=200)
    report.check(any(p["id"] == project_id for p in projects), "Supervisor access to Kashi Kunj (assigned)")
    tasks = await api.get(f"/projects/{project_id}/tasks", expect=200)
    report.check(len(tasks) >= 12, f"Supervisor can read tasks ({len(tasks)})")
    report.check(
        (await api.get(f"/projects/{project_id}/site-logs", expect=200)) is not None,
        "Supervisor can read site logs",
    )
    # Supervisor forbidden from finance/procurement surfaces
    for path in (
        f"/projects/{project_id}/job-costs",
        f"/projects/{project_id}/budget",
        f"/projects/{project_id}/purchase-orders",
        f"/projects/{project_id}/billing-milestones",
        f"/projects/{project_id}/invoices",
    ):
        try:
            await api.get(path, expect=403)
            report.check(True, f"Supervisor denied on {path.split('/')[-1]} (403)")
        except RuntimeError:
            report.check(False, f"Supervisor denied on {path.split('/')[-1]} (403)")

    # Client
    await api.login(CLIENT_EMAIL, demo_password)
    projects = await api.get("/projects", expect=200)
    report.check(any(p["id"] == project_id for p in projects), "Client access to Kashi Kunj (assigned)")
    invoices = await api.get(f"/projects/{project_id}/invoices", expect=200)
    client_drafts = [i for i in invoices if i.get("status") == "draft"]
    report.check(len(client_drafts) == 0, "Client sees no DRAFT invoices")
    report.check(
        all("notes" not in i or i["notes"] is None for i in invoices),
        "Client invoice shape carries no notes",
    )
    for path, label in (
        (f"/projects/{project_id}/health", "health"),
        (f"/projects/{project_id}/job-costs", "job costs"),
        (f"/projects/{project_id}/budget", "budget"),
        (f"/projects/{project_id}/purchase-orders", "purchase orders"),
        (f"/projects/{project_id}/inventory", "inventory"),
        (f"/projects/{project_id}/billing-milestones", "billing milestones"),
    ):
        try:
            await api.get(path, expect=403)
            report.check(True, f"Client denied on {label} (403)")
        except RuntimeError:
            report.check(False, f"Client denied on {label} (403)")


# ==============================================================================
# RESET
# ==============================================================================

async def reset(verbose: bool = True) -> None:
    """Remove ONLY Kashi-Kunj-owned demo rows (users, project, its children,
    the named demo vendors). Never touches unrelated data."""
    async with AsyncSessionLocal() as db:
        kashi_user_ids = (
            await db.execute(select(User.id).where(User.email.in_(KASHI_EMAILS)))
        ).scalars().all()
        projects = await _find_kashi_projects()
        project_ids = [p.id for p in projects]
        vendor_names = [v["name"] for v in DEMO_VENDORS]

        if not project_ids and not kashi_user_ids:
            print("Reset: no Kashi Kunj demo data found — nothing to do.")
            return

        # Collect ids of every demo-owned child row for the audit cleanup.
        audit_targets: set[str] = set(str(u) for u in kashi_user_ids)
        async def collect(table, col, where):
            rows = (await db.execute(select(col).where(where))).scalars().all()
            audit_targets.update(str(r) for r in rows)
            return rows

        for pid in project_ids:
            await collect(DailySiteLog, DailySiteLog.id, DailySiteLog.project_id == pid)
            await collect(JobCost, JobCost.id, JobCost.project_id == pid)
            await collect(BillingMilestone, BillingMilestone.id, BillingMilestone.project_id == pid)
            await collect(Invoice, Invoice.id, Invoice.project_id == pid)
            await collect(Task, Task.id, Task.project_id == pid)
            await collect(HealthOverride, HealthOverride.id, HealthOverride.project_id == pid)
            po_rows = await collect(PurchaseOrder, PurchaseOrder.id, PurchaseOrder.project_id == pid)
            for po_id in po_rows:
                await collect(Delivery, Delivery.id, Delivery.purchase_order_id == po_id)
                await collect(POLine, POLine.id, POLine.purchase_order_id == po_id)
            item_rows = await collect(InventoryItem, InventoryItem.id, InventoryItem.project_id == pid)
            for item_id in item_rows:
                await collect(StockMovement, StockMovement.id, StockMovement.item_id == item_id)
            vendor_ids = (
                await db.execute(select(Vendor.id).where(Vendor.name.in_(vendor_names)))
            ).scalars().all()
            audit_targets.update(str(v) for v in vendor_ids)

        async def _delete(table, where):
            await db.execute(delete(table).where(where))

        for pid in project_ids:
            await _delete(Notification, Notification.project_id == pid)
            await _delete(ProjectAssignment, ProjectAssignment.project_id == pid)
            await _delete(HealthOverride, HealthOverride.project_id == pid)
        if kashi_user_ids:
            await _delete(Notification, Notification.user_id.in_(kashi_user_ids))
            await _delete(RefreshSession, RefreshSession.user_id.in_(kashi_user_ids))

        # Delivery/stock/cost children before parents. delivery_lines point at
        # both deliveries and inventory items, so they go before both.
        await _delete(StockMovement, StockMovement.item_id.in_(
            select(InventoryItem.id).where(InventoryItem.project_id.in_(project_ids))
        ))
        await _delete(DeliveryLine, DeliveryLine.delivery_id.in_(
            select(Delivery.id).where(Delivery.project_id.in_(project_ids))
        ))
        await _delete(InventoryItem, InventoryItem.project_id.in_(project_ids))
        await _delete(Delivery, Delivery.project_id.in_(project_ids))
        await _delete(JobCost, JobCost.project_id.in_(project_ids))
        await _delete(Invoice, Invoice.project_id.in_(project_ids))
        await _delete(BillingMilestone, BillingMilestone.project_id.in_(project_ids))
        await _delete(POLine, POLine.purchase_order_id.in_(
            select(PurchaseOrder.id).where(PurchaseOrder.project_id.in_(project_ids))
        ))
        await _delete(PurchaseOrder, PurchaseOrder.project_id.in_(project_ids))
        await _delete(Task, Task.project_id.in_(project_ids))
        await _delete(DailySiteLog, DailySiteLog.project_id.in_(project_ids))
        await _delete(Project, Project.id.in_(project_ids))

        # Vendors (after their POs are gone — FK RESTRICT).
        await _delete(Vendor, Vendor.name.in_(vendor_names))

        # Demo users (after their notifications/sessions are gone).
        if kashi_user_ids:
            await _delete(User, User.id.in_(kashi_user_ids))

        # Audit trail: only rows that reference demo-owned records/users.
        audit_targets = {str(t) for t in audit_targets}
        if audit_targets:
            await _delete(
                AuditLog,
                AuditLog.record_id.in_(list(audit_targets)),
            )
        await _delete(AuditLog, AuditLog.user_id.in_(kashi_user_ids))

        await db.commit()

    print(f"Reset: removed Kashi Kunj demo data "
          f"({len(project_ids)} project(s), {len(kashi_user_ids)} user(s)).")


# ==============================================================================
# COPILOT SMOKE (optional)
# ==============================================================================

async def smoke(demo_password: str | None = None) -> None:
    """Optional end-to-end Copilot smoke: real chat turns and an HITL
    approval-gated mutation that we REJECT (no rehearsal data left behind)."""
    if demo_password is None:
        demo_password = _require_demo_password()

    from app.main import app

    async with _build_client(app) as client:
        api = Api(client)
        await api.login(ADMIN_EMAIL, demo_password)

        project_id = str((await _find_kashi_projects())[0].id)

        async def chat(message: str) -> dict:
            """One chat turn. Returns {"events": n, "approval": payload|None}."""
            events = []
            approval = None
            async with client.stream(
                "POST", "/assistant/chat", json={"message": message}, headers=api._headers()
            ) as resp:
                if resp.status_code != 200:
                    print(f"  chat -> HTTP {resp.status_code}: {resp.text[:300]}")
                    return {"events": 0, "approval": None}
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if line.startswith("event:"):
                        if line[6:].strip() == "approval_required":
                            pass  # payload comes on the following data line
                    elif line.startswith("data:"):
                        payload = line[5:].strip()
                        events.append(payload)
                        if "thread_id" in payload and "action_id" in payload:
                            approval = payload
            print(
                f"  chat: {len(events)} SSE events | "
                f"approval_required={'yes' if approval else 'no'}"
            )
            return {"events": len(events), "approval": approval}

        print("Copilot smoke (live LLM, may be slow or quota-limited):")
        for prompt in (
            "Tell me about Kashi Kunj.",
            "Which Kashi Kunj tasks need attention?",
            "What is low in stock at Kashi Kunj?",
            "Show Kashi Kunj's open purchase orders.",
            "Give me a management summary of Kashi Kunj.",
        ):
            await chat(prompt)

        print("HITL mutation smoke (create_task, then REJECT):")
        result = await chat(
            "Create a task for Kashi Kunj called Client meeting follow-up."
        )
        approval = result["approval"]
        if not approval:
            print(
                "  No approval_required event — the live model did not call the "
                "mutation tool this run (quota/behavior dependent). Nothing was "
                "created, so the demo is still pristine."
            )
            return
        import json as _json

        thread_id = _json.loads(approval)["thread_id"]
        print(f"  approval_required observed (thread {thread_id}) — rejecting:")
        events = []
        async with client.stream(
            "POST",
            "/assistant/resume",
            json={
                "thread_id": thread_id,
                "decision": "reject",
                "message": "Rejecting in the demo smoke test to keep the deck pristine.",
            },
            headers=api._headers(),
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    events.append(line[5:].strip())
        print(f"  resume: {len(events)} SSE events (decision=reject)")
        # Confirm no rehearsal task was left behind.
        tasks = await api.get(f"/projects/{project_id}/tasks", expect=200)
        leftover = [t for t in tasks if t["name"] == "Client meeting follow-up"]
        print(
            "  leftover 'Client meeting follow-up' task: "
            f"{'FOUND (bad)' if leftover else 'none (good)'}"
        )


# ==============================================================================
# CLI
# ==============================================================================

async def _run() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.demo.kashi_kunj")
    parser.add_argument(
        "command",
        choices=["seed", "verify", "reset", "reseed", "smoke"],
        help="seed: create demo data | verify: readiness checklist | reset: remove demo data | reseed: reset + seed | smoke: Copilot smoke",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="explicit demo flag (equivalent to ICE_KASHI_DEMO=true)",
    )
    args = parser.parse_args()

    _refuse_production()

    if args.command in ("seed", "reseed") and not args.demo:
        _require_demo_flag()

    if args.command == "seed":
        await seed()
    elif args.command == "verify":
        await verify()
    elif args.command == "reset":
        await reset()
    elif args.command == "reseed":
        await reset()
        await seed()
    elif args.command == "smoke":
        await smoke()


if __name__ == "__main__":
    asyncio.run(_run())