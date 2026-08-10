"""
Tests for the finance endpoints — job costing (Phase 3, M4).

Covers: create/update/delete JobCost (admin + procurement writers), RBAC
(supervisor cannot write, client cannot read the budget roll-up OR the
job-cost ledger), the core invariant that Project.budget_spent tracks the
SUM(job_costs) ledger after every mutation — including under concurrent
mutation (row-lock regression test) — plus the computed budget roll-up
endpoint.
"""
import asyncio
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.finance import _get_project_locked
from app.models.finance import JobCost
from app.models.project import Project
from app.models.user import User
from app.services.finance import refresh_budget_spent, sum_job_costs
from tests.conftest import TEST_DATABASE_URL, auth_header


def cost_payload(**overrides):
    payload = {
        "cost_code": "masonry",
        "description": "Cement blockwork — ground floor",
        "amount": 250000,
        "incurred_on": "2026-08-01",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_admin_creates_job_cost_and_budget_spent_updates(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/job-costs",
        headers={"Authorization": header},
        json=cost_payload(),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["cost_code"] == "masonry"
    assert body["amount"] == 250000.0

    # budget_spent on the project tracks the SUM(job_costs) ledger.
    project = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert project.json()["budget_spent"] == 250000.0


@pytest.mark.asyncio
async def test_job_costs_list_and_multiple_costs_sum(
    client: httpx.AsyncClient, test_procurement_user: User, test_project: Project
):
    header = await auth_header(client, "procurement@test.com")
    for amount in (100000, 150000):
        resp = await client.post(
            f"/api/v1/projects/{test_project.id}/job-costs",
            headers={"Authorization": header},
            json=cost_payload(amount=amount),
        )
        assert resp.status_code == 201

    listing = await client.get(
        f"/api/v1/projects/{test_project.id}/job-costs", headers={"Authorization": header}
    )
    assert listing.status_code == 200
    costs = listing.json()
    assert len(costs) == 2
    assert sum(c["amount"] for c in costs) == 250000.0

    project = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert project.json()["budget_spent"] == 250000.0


@pytest.mark.asyncio
async def test_budget_rollup_reports_spent_remaining_and_split(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    for payload in (
        cost_payload(amount=100000),
        cost_payload(cost_code="plumbing", amount=50000),
        cost_payload(cost_code="plumbing", amount=50000),
    ):
        resp = await client.post(
            f"/api/v1/projects/{test_project.id}/job-costs",
            headers={"Authorization": header},
            json=payload,
        )
        assert resp.status_code == 201

    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/budget", headers={"Authorization": header}
    )
    assert resp.status_code == 200
    rollup = resp.json()
    assert rollup["budget_total"] == 1000000.0
    assert rollup["budget_spent"] == 200000.0
    assert rollup["budget_remaining"] == 800000.0
    assert rollup["by_cost_code"] == {"masonry": 100000.0, "plumbing": 100000.0}


@pytest.mark.asyncio
async def test_update_job_cost_recomputes_budget_spent(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    created = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/job-costs",
            headers={"Authorization": header},
            json=cost_payload(amount=100000),
        )
    ).json()

    resp = await client.patch(
        f"/api/v1/projects/{test_project.id}/job-costs/{created['id']}",
        headers={"Authorization": header},
        json={"amount": 400000},
    )
    assert resp.status_code == 200
    assert resp.json()["amount"] == 400000.0

    project = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert project.json()["budget_spent"] == 400000.0


@pytest.mark.asyncio
async def test_delete_job_cost_recomputes_budget_spent(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    created = (
        await client.post(
            f"/api/v1/projects/{test_project.id}/job-costs",
            headers={"Authorization": header},
            json=cost_payload(amount=100000),
        )
    ).json()

    resp = await client.delete(
        f"/api/v1/projects/{test_project.id}/job-costs/{created['id']}",
        headers={"Authorization": header},
    )
    assert resp.status_code == 204

    project = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert project.json()["budget_spent"] == 0.0


@pytest.mark.asyncio
async def test_supervisor_cannot_write_job_costs(
    client: httpx.AsyncClient, test_supervisor_user: User, test_project: Project
):
    header = await auth_header(client, "supervisor@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/job-costs",
        headers={"Authorization": header},
        json=cost_payload(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_read_budget_rollup(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project, test_client_user: User
):
    header = await auth_header(client, "client@test.com")
    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/budget", headers={"Authorization": header}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_client_cannot_read_job_cost_ledger(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project, test_client_user: User
):
    """Cost line items/amounts are budget data: a client must get 403 on the
    job-cost ledger listing, not just on the aggregate budget roll-up."""
    header = await auth_header(client, "client@test.com")
    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/job-costs", headers={"Authorization": header}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_supervisor_cannot_read_job_cost_ledger(
    client: httpx.AsyncClient, test_supervisor_user: User, test_project: Project
):
    header = await auth_header(client, "supervisor@test.com")
    resp = await client.get(
        f"/api/v1/projects/{test_project.id}/job-costs", headers={"Authorization": header}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_concurrent_job_costs_no_lost_update(
    test_project: Project,
    test_procurement_user: User,
):
    """
    Regression test for the row-lock on job-cost mutations (PROBE-verified:
    WITHOUT `SELECT ... FOR UPDATE` on the project row this test FAILS, because
    the two transactions both read SUM(job_costs) before either commits and the
    last writer clobbers the total).

    Mirrors the endpoint's exact code path (lock project row -> insert cost ->
    refresh_budget_spent -> commit) across two real transactions with
    deterministic interleaving: T2 runs while T1's transaction is still
    uncommitted, then T2 commits LAST.
      - WITH the lock: T2 blocks on the project row until T1 commits, so its
        SUM sees T1's cost too -> budget_spent == 250000.
      - WITHOUT the lock: T2's SUM only sees its own cost -> budget_spent is
        clobbered to a partial total -> assertion fails.
    """
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    s1, s2 = Session(), Session()
    t1_committed = asyncio.Event()
    try:
        # T1 locks the project row and starts its own mutation, uncommitted.
        p1 = await _get_project_locked(s1, test_project.id)
        s1.add(
            JobCost(
                project_id=test_project.id,
                cost_code="masonry",
                description="Cement blockwork",
                amount=100000,
                incurred_on=date(2026, 8, 1),
            )
        )
        await s1.flush()

        async def run_t2() -> None:
            # Grab the project row (blocks behind T1's uncommitted lock when the
            # lock exists; proceeds immediately when it doesn't), record our
            # cost, recompute budget_spent, then commit LAST — i.e. after T1.
            p2 = await _get_project_locked(s2, test_project.id)
            s2.add(
                JobCost(
                    project_id=test_project.id,
                    cost_code="masonry",
                    description="Cement blockwork",
                    amount=150000,
                    incurred_on=date(2026, 8, 1),
                )
            )
            await s2.flush()
            await refresh_budget_spent(s2, p2)
            await t1_committed.wait()
            await s2.commit()

        t2_task = asyncio.create_task(run_t2())
        # Let T2 run its lock+insert+SUM while T1 is still uncommitted. With the
        # project row lock T2 stops at the FOR UPDATE; without it T2 computes a
        # stale SUM (only its own cost) and parks on t1_committed.
        await asyncio.sleep(0.2)

        # T1 computes its own SUM and commits first (releasing its row lock).
        await refresh_budget_spent(s1, p1)
        await s1.commit()
        t1_committed.set()
        await asyncio.wait_for(t2_task, timeout=5)

        # Ledger holds both costs; the denormalized total must too.
        ledger = await sum_job_costs(s1, test_project.id)
        assert ledger == Decimal("250000.00"), ledger
        s1.expire_all()  # drop s1's pre-commit snapshot of Project
        final = (
            await s1.execute(select(Project).where(Project.id == test_project.id))
        ).scalar_one()
        assert Decimal(str(final.budget_spent)) == ledger
    finally:
        t1_committed.set()
        if not t2_task.done():
            t2_task.cancel()
        await s1.close()
        await s2.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_zero_amount_rejected(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    resp = await client.post(
        f"/api/v1/projects/{test_project.id}/job-costs",
        headers={"Authorization": header},
        json=cost_payload(amount=0),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_nonexistent_cost_404(
    client: httpx.AsyncClient, test_admin_user: User, test_project: Project
):
    header = await auth_header(client, "admin@test.com")
    resp = await client.patch(
        f"/api/v1/projects/{test_project.id}/job-costs/{'00000000-0000-0000-0000-000000000000'}",
        headers={"Authorization": header},
        json={"amount": 10},
    )
    assert resp.status_code == 404