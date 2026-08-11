"""
Tests for Phase 3 M3 — deterministic computed project health + audited overrides.

Covers the pure rating formulas (threshold boundaries, lifecycle gating,
missing-data guards), the health endpoints (route-order regression, RBAC /
money isolation, override lifecycle), and the P0 seed ledger invariant.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from app.models.finance import CostCode, JobCost
from app.models.health import HealthOverride, HealthOverrideTarget, HealthOverrideValue
from app.models.project import HealthStatus, Project, ProjectStatus
from app.models.task import Task, TaskStatus
from app.services.health import (
    compute_health,
    rate_budget,
    rate_overall,
    rate_safety,
    rate_timeline,
)
from tests.conftest import TEST_DATABASE_URL, assign_user_to_project, auth_header

# ---------------------------------------------------------------- fixtures ---


def make_project(
    *,
    percent_complete: int = 0,
    start: date | None = None,
    end: date | None = None,
    status: ProjectStatus = ProjectStatus.ACTIVE,
    budget_total: Decimal | float = Decimal("1000000"),
    budget_spent: Decimal | float = 0,
) -> Project:
    """In-memory Project (no DB): only attribute reads, never flushed."""
    today = date.today()
    start_d = start or today - timedelta(days=90)
    return Project(
        project_code="PRJ-TEST-0001",
        name="Test Residence",
        site_address="123 Test Street",
        client_name="Test Client Co.",
        start_date=start_d,
        target_end_date=end or start_d + timedelta(days=365),
        status=status,
        percent_complete=percent_complete,
        budget_total=budget_total,
        budget_spent=budget_spent,
    )


def make_task(project: Project, *, end_date: date, status: TaskStatus = TaskStatus.IN_PROGRESS) -> Task:
    return Task(
        project_id=project.id,
        name="Foundation",
        start_date=project.start_date,
        end_date=end_date,
        status=status,
    )


def today() -> date:
    return date.today()


# ------------------------------------------------- timeline formula unit tests ---


@pytest.mark.parametrize(
    ("percent", "days_elapsed", "expected"),
    [
        (50, 80, HealthStatus.GREEN),   # SPI ~1.3 — well on track
        (50, 200, HealthStatus.AMBER),  # elapsed ~55%, SPI ~0.91
        (50, 240, HealthStatus.RED),    # elapsed ~66%, SPI ~0.76
    ],
)
def test_timeline_spi_thresholds(percent, days_elapsed, expected):
    start = today() - timedelta(days=days_elapsed)
    project = make_project(percent_complete=percent, start=start, end=start + timedelta(days=365))
    rating = rate_timeline(project, [], today())
    assert rating.rated is True
    assert rating.value == expected


def test_timeline_zero_duration_not_rated():
    start = today()
    project = make_project(percent_complete=50, start=start, end=start)
    rating = rate_timeline(project, [], today())
    assert rating.rated is False
    assert rating.value == HealthStatus.NOT_RATED


def test_timeline_not_started_yet_not_rated():
    project = make_project(percent_complete=0, start=today() - timedelta(days=3))
    rating = rate_timeline(project, [], today())
    assert rating.rated is False
    assert rating.value == HealthStatus.NOT_RATED


def test_timeline_just_started_is_green():
    project = make_project(percent_complete=10, start=today() - timedelta(days=5))
    rating = rate_timeline(project, [make_task(project, end_date=today() + timedelta(days=30))], today())
    assert rating.value == HealthStatus.GREEN
    assert "Just started" in rating.reasons[0]


def test_timeline_zero_progress_green_after_early_band():
    project = make_project(percent_complete=0, start=today() - timedelta(days=200))
    rating = rate_timeline(project, [], today())
    assert rating.value == HealthStatus.GREEN


def test_timeline_elapsed_clamped_to_full():
    project = make_project(percent_complete=40, start=today() - timedelta(days=1500))
    rating = rate_timeline(project, [], today())
    assert rating.rated is True
    assert rating.value == HealthStatus.RED  # progress far behind elapsed-saturated


def test_timeline_overdue_downgrades_to_red():
    project = make_project(percent_complete=95)
    tasks = [
        make_task(project, end_date=today() - timedelta(days=5))
        for _ in range(3)
    ]  # 3/3 overdue — fraction > 0.40
    rating = rate_timeline(project, tasks, today())
    assert rating.value == HealthStatus.RED


def test_timeline_overdue_downgrades_amber_but_not_beyond_red():
    project = make_project(percent_complete=95)
    tasks = [
        make_task(project, end_date=today() - timedelta(days=5)),  # overdue
        make_task(project, end_date=today() + timedelta(days=10)),  # on time
        make_task(project, end_date=today() + timedelta(days=20)),  # on time
    ]  # fraction 1/3 ~0.33 — only the AMBER downgrade applies
    rating = rate_timeline(project, tasks, today())
    assert rating.value == HealthStatus.AMBER
    assert "overdue" in rating.reasons[1]


def test_timeline_overdue_never_upgrades():
    # SPI verdict is RED; overdue count is zero, so RED must survive.
    project = make_project(percent_complete=20, start=today() - timedelta(days=240))
    tasks = [
        make_task(project, end_date=today() + timedelta(days=10), status=TaskStatus.COMPLETED)
    ]
    rating = rate_timeline(project, tasks, today())
    assert rating.value == HealthStatus.RED


def test_timeline_draft_and_on_hold_not_rated():
    draft = make_project(status=ProjectStatus.DRAFT)
    assert rate_timeline(draft, [], today()).value == HealthStatus.NOT_RATED

    on_hold = make_project(status=ProjectStatus.ON_HOLD)
    hold_rating = rate_timeline(on_hold, [], today())
    assert hold_rating.value == HealthStatus.NOT_RATED
    assert "on hold" in hold_rating.reasons[0].lower()


def test_timeline_deterministic():
    project = make_project(percent_complete=60, start=today() - timedelta(days=100))
    first = rate_timeline(project, [], today())
    second = rate_timeline(project, [], today())
    assert first.value == second.value
    assert first.reasons == second.reasons


# -------------------------------------------------- budget formula unit tests ---


@pytest.mark.parametrize(
    ("percent", "spent_frac", "expected"),
    [
        (50, "0.50", HealthStatus.GREEN),  # consumed == progress
        (50, "0.54", HealthStatus.GREEN),  # within +5pp
        (50, "0.55", HealthStatus.GREEN),  # exactly the GREEN boundary
        (50, "0.60", HealthStatus.AMBER),  # within +15pp
        (50, "0.65", HealthStatus.AMBER),  # exactly the AMBER boundary
        (50, "0.70", HealthStatus.RED),    # beyond +15pp
    ],
)
def test_budget_thresholds(percent, spent_frac, expected):
    project = make_project(percent_complete=percent)
    spent = Decimal(spent_frac) * Decimal(project.budget_total)
    rating = rate_budget(project, spent, today())
    assert rating.rated is True
    assert rating.value == expected


def test_budget_zero_total_not_rated():
    project = make_project(budget_total=0)
    assert rate_budget(project, Decimal("0"), today()).value == HealthStatus.NOT_RATED


def test_budget_zero_spend_early_is_green():
    project = make_project(percent_complete=10)
    rating = rate_budget(project, Decimal("0"), today())
    assert rating.value == HealthStatus.GREEN


def test_budget_zero_spend_with_progress_is_untracked():
    project = make_project(percent_complete=40)
    rating = rate_budget(project, Decimal("0"), today())
    assert rating.value == HealthStatus.NOT_RATED
    assert "zero job costs" in rating.reasons[0]


def test_budget_uses_ledger_not_denormalized_column():
    project = make_project(percent_complete=50, budget_spent=0)  # column says 0
    rating = rate_budget(project, Decimal("600000"), today())  # ledger says 60%
    assert rating.value == HealthStatus.AMBER  # 0.60 vs 0.50 progress


def test_budget_near_completion_small_overrun_is_green():
    project = make_project(percent_complete=96)
    rating = rate_budget(project, Decimal("1010000"), today())  # consumed 1.01 vs 0.96
    assert rating.value == HealthStatus.GREEN


def test_budget_worst_case_wording():
    project = make_project(percent_complete=50)
    rating = rate_budget(project, Decimal("700000"), today())
    assert "percentage points" in rating.reasons[0]
    assert "ahead of reported physical progress" in rating.reasons[0]


def test_budget_not_rated_when_not_active():
    project = make_project(status=ProjectStatus.PLANNING)
    assert rate_budget(project, Decimal("100000"), today()).value == HealthStatus.NOT_RATED


# ------------------------------------------------- overall formula unit tests ---


def test_overall_worst_of_rated():
    timeline = rate_timeline(make_project(percent_complete=99), [], today())
    budget = rate_budget(
        make_project(percent_complete=50), Decimal("600000"), today()
    )  # AMBER
    safety = rate_safety()
    overall = rate_overall(timeline, budget, safety)
    assert overall.value == HealthStatus.AMBER
    assert overall.basis == ["timeline", "budget"]


def test_overall_not_rated_when_everything_unrated():
    project = make_project(status=ProjectStatus.DRAFT)
    overall = rate_overall(
        rate_timeline(project, [], today()),
        rate_budget(project, Decimal("0"), today()),
        rate_safety(),
    )
    assert overall.value == HealthStatus.NOT_RATED
    assert overall.rated is False


def test_overall_deterministic():
    p = make_project(percent_complete=50)
    a = rate_overall(rate_timeline(p, [], today()), rate_budget(p, Decimal("100000"), today()), rate_safety())
    b = rate_overall(rate_timeline(p, [], today()), rate_budget(p, Decimal("100000"), today()), rate_safety())
    assert a.value == b.value
    assert a.basis == b.basis


# ----------------------------------------------- compute_health + overrides ---


def test_override_applies_to_effective_only():
    project = make_project(percent_complete=50)
    override = HealthOverride(
        project_id=project.id,
        applied_to=HealthOverrideTarget.BUDGET,
        value=HealthOverrideValue.RED,
        reason="Director board decision to flag this site.",
        expires_at=None,
        revoked_at=None,
    )
    from app.services.health import HealthContext

    state = compute_health(project, HealthContext(spent_ledger=Decimal("600000"), overrides=[override]), today())
    assert state.budget.value == HealthStatus.AMBER   # computed unchanged
    assert state.effective_budget == HealthStatus.RED  # override active
    assert state.effective_timeline == state.timeline.value
    assert state.overall.value == HealthStatus.AMBER
    assert state.effective_overall == HealthStatus.AMBER


def test_expired_override_is_inert():
    project = make_project(percent_complete=50)
    override = HealthOverride(
        project_id=project.id,
        applied_to=HealthOverrideTarget.BUDGET,
        value=HealthOverrideValue.RED,
        reason="Temporary freeze pending review sign off.",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    from app.services.health import HealthContext

    state = compute_health(project, HealthContext(spent_ledger=Decimal("600000"), overrides=[override]), today())
    assert state.effective_budget == HealthStatus.AMBER


def test_completed_project_frozen_and_computed():
    project = make_project(percent_complete=100, status=ProjectStatus.COMPLETED)
    from app.services.health import HealthContext

    state = compute_health(project, HealthContext(spent_ledger=Decimal("500000")), today())
    assert state.frozen is True
    assert state.timeline.rated is True


def test_archived_and_draft_not_computed():
    from app.services.health import HealthContext

    archived = make_project(status=ProjectStatus.ARCHIVED)
    state = compute_health(archived, HealthContext(), today())
    assert state.frozen is True
    assert state.timeline.rated is False
    assert "Archived" in state.timeline.reasons[0]

    draft = make_project(status=ProjectStatus.DRAFT)
    assert compute_health(draft, HealthContext(), today()).overall.value == HealthStatus.NOT_RATED


# --------------------------------------------------------- API integration ---


@pytest.mark.asyncio
async def test_health_rollup_not_shadowed_and_matches_detail(
    client: httpx.AsyncClient,
    test_admin_user,
    test_db,
    test_project,
):
    """GET /projects/health must be reachable (route-order regression) and the
    roll-up verdict per project matches the single-project endpoint."""
    header = await auth_header(client, "admin@test.com")

    rollup = await client.get("/api/v1/projects/health", headers={"Authorization": header})
    assert rollup.status_code == 200, rollup.text
    body = rollup.json()
    assert isinstance(body, list)
    assert len(body) == 1  # only the bare test_project (ARCHIVED hidden)

    detail = await client.get(
        f"/api/v1/projects/{test_project.id}/health", headers={"Authorization": header}
    )
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["project_id"] == str(test_project.id)
    for key in ("timeline", "budget", "safety", "overall", "data_sufficiency"):
        assert key in detail_body
    # No monetary fields anywhere in the health payload.
    txt = rollup.text
    assert "budget_total" not in txt and "budget_spent" not in txt


@pytest.mark.asyncio
async def test_health_budget_verdict_from_ledger(
    client: httpx.AsyncClient, test_admin_user, test_db, test_project
):
    header = await auth_header(client, "admin@test.com")

    # 60% spent against a 50%-complete ACTIVE project -> AMBER on budget
    # (consumption 10pp ahead of physical progress).
    test_project.percent_complete = 50
    test_db.add(
        JobCost(
            project_id=test_project.id,
            cost_code=CostCode.STRUCTURE,
            description="Structural steel",
            amount=Decimal("600000"),
            incurred_on=date.today(),
        )
    )
    await test_db.commit()

    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/health", headers={"Authorization": header}
    )
    budget = resp.json()["budget"]
    assert budget["effective"] == "amber"
    assert "percentage points" in budget["reasons"][0]


@pytest.mark.asyncio
async def test_supervisor_client_get_no_money(
    client: httpx.AsyncClient,
    test_admin_user,
    test_supervisor_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    # Supervisor: no money on project reads, but health stays readable (M6 —
    # health is a supervisor surface; only clients lose it).
    sup_header = await auth_header(client, "supervisor@test.com")
    listing = await client.get("/api/v1/projects", headers={"Authorization": sup_header})
    assert listing.status_code == 200
    item = listing.json()[0]
    assert "budget_total" not in item
    assert "budget_spent" not in item

    one = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": sup_header}
    )
    assert one.status_code == 200
    assert "budget_total" not in one.json()
    assert "budget_spent" not in one.json()

    health = await client.get(
        f"/api/v1/projects/{test_project.id}/health", headers={"Authorization": sup_header}
    )
    assert health.status_code == 200
    assert "budget_total" not in health.text
    assert "budget_spent" not in health.text
    # Health colors + reasons stay visible to supervisors (budget colour only).
    assert "timeline" in health.json()

    # Client (M6): project reads are no-money and health is 403 — computed
    # health is an internal management signal, not part of the client portal.
    client_header = await auth_header(client, "client@test.com")
    clisting = await client.get("/api/v1/projects", headers={"Authorization": client_header})
    assert clisting.status_code == 200
    citem = clisting.json()[0]
    assert "budget_total" not in citem
    assert "budget_spent" not in citem
    # Client project shape also drops internal attribution columns.
    for internal in ("budget_total", "budget_spent", "created_by", "completed_by", "archived_by", "restored_by"):
        assert internal not in citem

    chealth = await client.get(
        f"/api/v1/projects/{test_project.id}/health", headers={"Authorization": client_header}
    )
    assert chealth.status_code == 403


@pytest.mark.asyncio
async def test_admin_procurement_keep_money_and_see_override_history(
    client: httpx.AsyncClient, test_admin_user, test_procurement_user, test_db, test_project
):
    admin_header = await auth_header(client, "admin@test.com")
    item = (await client.get("/api/v1/projects", headers={"Authorization": admin_header})).json()[0]
    assert "budget_total" in item and "budget_spent" in item

    proc_header = await auth_header(client, "procurement@test.com")
    proc_item = (
        await client.get("/api/v1/projects", headers={"Authorization": proc_header})
    ).json()[0]
    assert "budget_total" in proc_item and "budget_spent" in proc_item

    # Procurement can read full health incl. (empty) override history.
    health = await client.get(
        f"/api/v1/projects/{test_project.id}/health", headers={"Authorization": proc_header}
    )
    assert "overrides" in health.json()


@pytest.mark.asyncio
async def test_client_isolated_from_other_project(
    client: httpx.AsyncClient, test_admin_user, test_client_user, test_db, test_project
):
    client_header = await auth_header(client, "client@test.com")
    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/health", headers={"Authorization": client_header}
    )
    # 403 on both counts: the client is un-assigned AND (M6) health is not a
    # client surface at all — either way, never 200 with health data.
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_override_lifecycle_and_audit(
    client: httpx.AsyncClient, test_admin_user, test_db, test_project
):
    admin_header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}"

    # reason min-length enforced (422 on validation)
    short = await client.post(
        f"{url}/health-overrides",
        headers={"Authorization": admin_header},
        json={"applied_to": "budget", "value": "amber", "reason": "too short"},
    )
    assert short.status_code == 422

    # not_rated is not a valid override verdict
    bad = await client.post(
        f"{url}/health-overrides",
        headers={"Authorization": admin_header},
        json={"applied_to": "budget", "value": "not_rated", "reason": "A very clear and long reason."},
    )
    assert bad.status_code == 422

    first = await client.post(
        f"{url}/health-overrides",
        headers={"Authorization": admin_header},
        json={"applied_to": "budget", "value": "red", "reason": "Budget flagged by the steering committee."},
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    # effective flips to red while computed stays green (ACTIVE, zero spend early).
    health = (await client.get(f"{url}/health", headers={"Authorization": admin_header})).json()
    assert health["budget"]["effective"] == "red"
    assert health["budget"]["value"] == "green"

    # Second set on the same target auto-revokes the first (single-active).
    second = await client.post(
        f"{url}/health-overrides",
        headers={"Authorization": admin_header},
        json={"applied_to": "budget", "value": "amber", "reason": "Re-forecast after materials landed."},
    )
    assert second.status_code == 201
    history = (
        await client.get(f"{url}/health-overrides", headers={"Authorization": admin_header})
    ).json()
    assert len(history) == 2
    by_id = {row["id"]: row for row in history}
    assert by_id[first_id]["active"] is False  # revoked by the second set
    assert by_id[second.json()["id"]]["active"] is True

    # Revoke restores the computed verdict.
    revoke = await client.delete(
        f"{url}/health-overrides/{second.json()['id']}", headers={"Authorization": admin_header}
    )
    assert revoke.status_code == 204
    health = (await client.get(f"{url}/health", headers={"Authorization": admin_header})).json()
    assert health["budget"]["effective"] == health["budget"]["value"]

    # Audit trail recorded both the override and the revokation.
    logs = (
        await client.get("/api/v1/audit/logs", headers={"Authorization": admin_header})
    ).json()
    actions = {row["action"] for row in logs}
    assert "health_override" in actions
    assert "health_override_revoked" in actions


@pytest.mark.asyncio
async def test_override_admin_only_and_archived_blocked(
    client: httpx.AsyncClient,
    test_admin_user,
    test_supervisor_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    supervisor_header = await auth_header(client, "supervisor@test.com")
    admin_header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}"

    forbid = await client.post(
        f"{url}/health-overrides",
        headers={"Authorization": supervisor_header},
        json={"applied_to": "timeline", "value": "amber", "reason": "Supervisor wants to flag the schedule."},
    )
    assert forbid.status_code == 403

    # Archives are read-only for overrides: ACTIVE -> COMPLETED -> ARCHIVED.
    assert (await client.post(f"{url}/complete", headers={"Authorization": admin_header})).status_code == 200
    assert (await client.post(f"{url}/archive", headers={"Authorization": admin_header})).status_code == 200
    blocked = await client.post(
        f"{url}/health-overrides",
        headers={"Authorization": admin_header},
        json={"applied_to": "timeline", "value": "amber", "reason": "Trying to override an archived project."},
    )
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_lifecycle_health_and_archived_exclusion(
    client: httpx.AsyncClient,
    test_admin_user,
    test_supervisor_user,
    test_db,
    test_project,
):
    admin_header = await auth_header(client, "admin@test.com")
    url = f"/api/v1/projects/{test_project.id}"

    # DRAFT first: create via API (create lands in DRAFT), expect all NOT_RATED.
    created = await client.post(
        "/api/v1/projects",
        headers={"Authorization": admin_header},
        json={
            "name": "Draft Site",
            "site_address": "1 Draft Lane",
            "client_name": "Draft Co.",
            "start_date": str(date.today()),
            "target_end_date": str(date.today() + timedelta(days=300)),
            "budget_total": 5000000,
        },
    )
    draft_id = created.json()["id"]
    draft_health = (
        await client.get(f"/api/v1/projects/{draft_id}/health", headers={"Authorization": admin_header})
    ).json()
    assert draft_health["timeline"]["rated"] is False
    assert draft_health["budget"]["rated"] is False
    assert draft_health["overall"]["value"] == "not_rated"

    # ACTIVE -> COMPLETED: frozen flag flips on.
    assert (await client.post(f"{url}/complete", headers={"Authorization": admin_header})).status_code == 200
    completed_health = (
        await client.get(f"{url}/health", headers={"Authorization": admin_header})
    ).json()
    assert completed_health["frozen"] is True

    # ARCHIVED: excluded from normal roll-up, visible to admin with include_archived.
    assert (await client.post(f"{url}/archive", headers={"Authorization": admin_header})).status_code == 200
    rollup = await client.get("/api/v1/projects/health", headers={"Authorization": admin_header})
    assert all(p["project_id"] != str(test_project.id) for p in rollup.json())
    with_archived = await client.get(
        "/api/v1/projects/health?include_archived=true", headers={"Authorization": admin_header}
    )
    ids = [p["project_id"] for p in with_archived.json()]
    assert str(test_project.id) in ids
    archived_health = next(
        p for p in with_archived.json() if p["project_id"] == str(test_project.id)
    )
    assert archived_health["timeline"]["rated"] is False

    # Non-admin health roll-up excludes archived even when asked to include.
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)
    sup_header = await auth_header(client, "supervisor@test.com")
    sup_rollup = await client.get(
        "/api/v1/projects/health?include_archived=true", headers={"Authorization": sup_header}
    )
    assert all(p["project_id"] != str(test_project.id) for p in sup_rollup.json())


@pytest.mark.asyncio
async def test_seed_maintains_budget_ledger_invariant(test_db):
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.models.finance import JobCost
    from app.models.project import Project
    from app.seed import seed

    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        await seed(factory, force=True)

        async with factory() as db:
            rows = (
                await db.execute(
                    select(
                        Project.project_code,
                        Project.budget_spent,
                        func.coalesce(func.sum(JobCost.amount), 0).label("ledger"),
                        Project.timeline_health,
                    )
                    .outerjoin(JobCost, JobCost.project_id == Project.id)
                    .group_by(Project.id)
                )
            ).all()
            assert len(rows) >= 1
            for code, spent, ledger, manual_timeline in rows:
                assert Decimal(str(spent)) == Decimal(str(ledger)), (
                    f"budget_spent != SUM(job_costs) for {code}"
                )
                # M3: seed no longer fabricates random manual health colors.
                assert manual_timeline == HealthStatus.GREEN
    finally:
        await engine.dispose()