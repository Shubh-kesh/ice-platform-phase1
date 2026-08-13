"""
M6 — Client portal boundary tests.

The CLIENT role is the portal-facing persona. These tests pin the exact
server-side contract the SPA client portal depends on:

  * Project reads: the tight ProjectClientRead shape on both list and detail
    — no budget figures, no manual health columns, no lifecycle attribution
    (created_by/completed_by/archived_by/restored_by), no internal
    created_at/updated_at bookkeeping.
  * Health: 403 for clients on both the roll-up and per-project endpoints —
    computed health (colors, reasons, basis) is an internal management signal,
    not part of the client portal.
  * Inventory/procurement: 403 for clients — the stock-movement ledger and
    unit costs are internal.
  * Invoices: clients see issued payment requests only. DRAFT invoices are
    hidden from the list and return 404 on detail (their existence is never
    leaked). SENT/PAID/CANCELLED return the restricted InvoiceClientRead
    shape.
  * Writes: clients are read-only in this phase — the role-gated write
    endpoints already reject with 403 (asserted for tasks, milestones and
    inventory for the record).

Close-out additions (M6): project detail isolation, archived-project 404,
client task/site-log read *shape* (not just status), invoice field
allow-list/deny-list, an IDOR check across tasks/site-logs/inventory,
a consolidated mutation matrix, Google-authenticated-client parity, and a
compact role regression for admin/procurement/supervisor.
"""
import time
import uuid

import httpx
import pytest

from app.core.config import settings
from tests.conftest import assign_user_to_project, auth_header


CLIENT_FORBIDDEN_KEYS = {
    "budget_total",
    "budget_spent",
    "timeline_health",
    "budget_health",
    "safety_health",
    "created_by",
    "completed_by",
    "archived_by",
    "restored_by",
    "archived_at",
    "restored_at",
    "created_at",
    "updated_at",
}

CLIENT_PRESENT_KEYS = {
    "id",
    "project_code",
    "name",
    "site_address",
    "client_name",
    "start_date",
    "target_end_date",
    "status",
    "percent_complete",
    "completed_at",
}

CLIENT_INVOICE_FORBIDDEN_KEYS = {
    "billing_milestone_id",
    "notes",
    "issued_by",
    "paid_by",
    "cancelled_by",
    "updated_at",
}

# Money/procurement fields that must never appear in ANY client-visible
# payload — including tasks/site-logs reads (which do carry their own benign
# created_at/updated_at progress metadata).
CLIENT_MONEY_KEYS = {
    "budget_total",
    "budget_spent",
    "unit_cost",
    "quantity_on_hand",
    "amount",
    "fixed_amount",
    "billing_percentage",
}


async def create_milestone(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, **overrides
):
    payload = {
        "name": "Foundation",
        "billing_type": "percentage",
        "billing_percentage": 20,
        "sort_order": 1,
        "description": "Ground floor + slab",
    }
    payload.update(overrides)
    return await client.post(
        f"/api/v1/projects/{project_id}/billing-milestones",
        headers={"Authorization": header},
        json=payload,
    )


async def complete_milestone(
    client: httpx.AsyncClient, header: str, project_id: uuid.UUID, milestone_id: uuid.UUID
):
    return await client.post(
        f"/api/v1/projects/{project_id}/billing-milestones/{milestone_id}/complete",
        headers={"Authorization": header},
    )


async def make_invoice(
    client: httpx.AsyncClient,
    header: str,
    project_id: uuid.UUID,
    milestone_id: uuid.UUID,
    **overrides,
):
    payload = {"billing_milestone_id": str(milestone_id)}
    payload.update(overrides)
    return await client.post(
        f"/api/v1/projects/{project_id}/invoices",
        headers={"Authorization": header},
        json=payload,
    )


async def create_second_project(client: httpx.AsyncClient, header: str) -> uuid.UUID:
    resp = await client.post(
        "/api/v1/projects",
        headers={"Authorization": header},
        json={
            "name": "Other Site",
            "site_address": "456 Elsewhere Street",
            "client_name": "Other Co.",
            "start_date": "2026-02-01",
            "target_end_date": "2026-11-30",
            "budget_total": 500000,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- Project reads: the tight client shape ----------------------------------


@pytest.mark.asyncio
async def test_client_project_shape_list_and_detail(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")

    listing = await client.get("/api/v1/projects", headers={"Authorization": header})
    assert listing.status_code == 200
    (item,) = listing.json()
    assert CLIENT_PRESENT_KEYS <= set(item.keys())
    assert not (set(item.keys()) & CLIENT_FORBIDDEN_KEYS)

    one = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert one.status_code == 200
    assert CLIENT_PRESENT_KEYS <= set(one.json().keys())
    assert not (set(one.json().keys()) & CLIENT_FORBIDDEN_KEYS)


@pytest.mark.asyncio
async def test_client_only_own_projects_in_list(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    # A second project the client is NOT assigned to must never appear.
    admin = await auth_header(client, "admin@test.com")
    other_id = await create_second_project(client, admin)

    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")
    listing = await client.get("/api/v1/projects", headers={"Authorization": header})
    assert listing.status_code == 200
    ids = {p["id"] for p in listing.json()}
    assert ids == {str(test_project.id)}
    assert other_id not in ids


# --- Health is an internal management signal --------------------------------


@pytest.mark.asyncio
async def test_client_health_forbidden(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")

    rollup = await client.get("/api/v1/projects/health", headers={"Authorization": header})
    assert rollup.status_code == 403

    one = await client.get(
        f"/api/v1/projects/{test_project.id}/health", headers={"Authorization": header}
    )
    assert one.status_code == 403


# --- Inventory / procurement is an internal surface -------------------------


@pytest.mark.asyncio
async def test_client_inventory_403(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")
    created = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory",
        headers={"Authorization": admin},
        json={"name": "Cement", "unit": "bag", "unit_cost": 12.5, "opening_quantity": 100},
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    header = await auth_header(client, "client@test.com")
    items = await client.get(
        f"/api/v1/projects/{test_project.id}/inventory", headers={"Authorization": header}
    )
    assert items.status_code == 403

    movements = await client.get(
        f"/api/v1/projects/{test_project.id}/inventory/{item_id}/movements",
        headers={"Authorization": header},
    )
    assert movements.status_code == 403


# --- Invoices: issued only, restricted shape --------------------------------


@pytest.mark.asyncio
async def test_client_draft_invoice_hidden_and_sent_visible(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")

    m = (await create_milestone(client, admin, test_project.id)).json()
    await complete_milestone(client, admin, test_project.id, m["id"])
    draft = (await make_invoice(client, admin, test_project.id, m["id"])).json()
    assert draft["status"] == "draft"

    header = await auth_header(client, "client@test.com")
    # DRAFT is filtered out of the client's list...
    listing = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": header}
    )
    assert listing.status_code == 200
    assert listing.json() == []
    # ...and 404s on detail (existence never leaked).
    one = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices/{draft['id']}",
        headers={"Authorization": header},
    )
    assert one.status_code == 404

    # Issue -> SENT: now visible in the restricted client shape.
    issued = await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{draft['id']}/issue",
        headers={"Authorization": admin},
    )
    assert issued.status_code == 200

    listing = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": header}
    )
    assert listing.status_code == 200
    (item,) = listing.json()
    assert item["status"] == "sent"
    assert item["overdue"] in (True, False)
    assert not (set(item.keys()) & CLIENT_INVOICE_FORBIDDEN_KEYS)

    one = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices/{draft['id']}",
        headers={"Authorization": header},
    )
    assert one.status_code == 200
    assert one.json()["status"] == "sent"


@pytest.mark.asyncio
async def test_client_cannot_see_unassigned_project_invoices(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    admin = await auth_header(client, "admin@test.com")
    other_id = await create_second_project(client, admin)
    # Client assigned only to the fixture project, not the second one.
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    header = await auth_header(client, "client@test.com")
    listing = await client.get(
        f"/api/v1/projects/{other_id}/invoices", headers={"Authorization": header}
    )
    assert listing.status_code == 403


# --- Clients are read-only in this phase ------------------------------------


@pytest.mark.asyncio
async def test_client_write_endpoints_403(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")

    task = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": header},
        json={"name": "Pour slab", "start_date": "2026-01-15", "end_date": "2026-01-20"},
    )
    assert task.status_code == 403

    milestone = await create_milestone(client, header, test_project.id)
    assert milestone.status_code == 403

    inventory = await client.post(
        f"/api/v1/projects/{test_project.id}/inventory",
        headers={"Authorization": header},
        json={"name": "Cement", "unit": "bag"},
    )
    assert inventory.status_code == 403


# --- M6 close-out: isolation, shape, IDOR, parity, role regression -----------


async def _google_login_as(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    google_jwks,
    email: str,
) -> str:
    """Complete a real Google callback for an existing ICE user (M11 link/login
    path) and return the access token. Google must NOT change authorization."""
    authz = (await client.get("/api/v1/auth/google/authorize")).json()
    now = int(time.time())
    claims = {
        "iss": "accounts.google.com",
        "aud": settings.GOOGLE_CLIENT_ID,
        "sub": f"google-sub-{email.split('@')[0]}",
        "email": email,
        "email_verified": True,
        "name": "Google Client",
        "iat": now - 5,
        "nbf": now - 5,
        "exp": now + 3600,
        "nonce": authz["nonce"],
    }
    token = google_jwks["sign"](claims)
    monkeypatch.setattr(
        "app.services.google_auth._fetch_google_certs", lambda: google_jwks["certs"]
    )
    monkeypatch.setattr(
        "app.services.google_auth.exchange_code_for_tokens",
        lambda code, verifier: {"id_token": token},
    )
    resp = await client.post(
        "/api/v1/auth/google/callback",
        json={
            "code": "auth-code-parity",
            "code_verifier": authz["code_verifier"],
            "state": authz["state"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_client_project_detail_isolation(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    """Assigned client views their project; an unassigned project's detail is 403."""
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")

    own = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert own.status_code == 200

    other_id = await create_second_project(client, await auth_header(client, "admin@test.com"))
    denied = await client.get(
        f"/api/v1/projects/{other_id}", headers={"Authorization": header}
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_client_archived_project_404(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    """M10 contract: ARCHIVED projects are 404 to clients — even when assigned."""
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")
    archived = await client.post(
        f"/api/v1/projects/{test_project.id}/archive", headers={"Authorization": admin}
    )
    assert archived.status_code == 200

    header = await auth_header(client, "client@test.com")
    detail = await client.get(
        f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
    )
    assert detail.status_code == 404
    invoices = await client.get(
        f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": header}
    )
    assert invoices.status_code == 404


@pytest.mark.asyncio
async def test_client_task_and_site_log_read_shape(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    """Client may read tasks/site-logs on an assigned project, but only the
    project-scoped fields — and can never mutate them."""
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")
    await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers={"Authorization": admin},
        json={"name": "Roofing", "start_date": "2026-03-01", "end_date": "2026-04-01"},
    )
    await client.post(
        f"/api/v1/projects/{test_project.id}/site-logs",
        headers={"Authorization": admin},
        json={"log_date": "2026-08-09", "work_summary": "Site progress."},
    )

    header = await auth_header(client, "client@test.com")
    tasks = await client.get(
        f"/api/v1/projects/{test_project.id}/tasks", headers={"Authorization": header}
    )
    assert tasks.status_code == 200
    (task,) = tasks.json()
    assert {"id", "name", "status", "percent_complete", "start_date", "end_date"} <= set(task.keys())
    assert not (set(task.keys()) & CLIENT_MONEY_KEYS)

    logs = await client.get(
        f"/api/v1/projects/{test_project.id}/site-logs", headers={"Authorization": header}
    )
    assert logs.status_code == 200
    (log,) = logs.json()
    assert {"id", "log_date", "work_summary"} <= set(log.keys())
    assert not (set(log.keys()) & CLIENT_MONEY_KEYS)

    patch = await client.patch(
        f"/api/v1/projects/{test_project.id}/tasks/{task['id']}",
        headers={"Authorization": header},
        json={"status": "completed"},
    )
    assert patch.status_code == 403


@pytest.mark.asyncio
async def test_client_invoice_shape_allow_and_deny(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    """The client invoice shape must contain amount/overdue and nothing from the
    internal finance set (notes, billing rules, external sync, attribution)."""
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")
    m = (await create_milestone(client, admin, test_project.id)).json()
    await complete_milestone(client, admin, test_project.id, m["id"])
    inv = (await make_invoice(client, admin, test_project.id, m["id"])).json()
    await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/issue",
        headers={"Authorization": admin},
    )

    header = await auth_header(client, "client@test.com")
    (item,) = (
        await client.get(
            f"/api/v1/projects/{test_project.id}/invoices", headers={"Authorization": header}
        )
    ).json()
    assert item["amount"] == inv["amount"]
    assert "overdue" in item
    assert not (set(item.keys()) & CLIENT_INVOICE_FORBIDDEN_KEYS)
    assert "billing_percentage" not in item
    assert "fixed_amount" not in item
    assert "external_ref" not in item and "external_sync_status" not in item
    assert "notes" not in item


@pytest.mark.asyncio
async def test_client_unassigned_invoice_detail_403(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    """Unassigned project's invoice detail is 403 before any lookup happens."""
    admin = await auth_header(client, "admin@test.com")
    other_id = await create_second_project(client, admin)
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    header = await auth_header(client, "client@test.com")
    resp = await client.get(
        f"/api/v1/projects/{other_id}/invoices/{uuid.uuid4()}",
        headers={"Authorization": header},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_client_financial_isolation_across_surfaces(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    """Clients never receive money/internal fields in project reads and are 403
    on every financial/procurement/health surface — even on an assigned project."""
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")
    await client.post(
        f"/api/v1/projects/{test_project.id}/inventory",
        headers={"Authorization": admin},
        json={"name": "Steel", "unit": "ton", "unit_cost": 1000, "opening_quantity": 5},
    )
    await client.post(
        f"/api/v1/projects/{test_project.id}/job-costs",
        headers={"Authorization": admin},
        json={
            "cost_code": "structure",
            "description": "Steel",
            "amount": 5000,
            "incurred_on": "2026-08-01",
        },
    )

    header = await auth_header(client, "client@test.com")
    project = (
        await client.get(
            f"/api/v1/projects/{test_project.id}", headers={"Authorization": header}
        )
    ).json()
    for key in (
        "budget_total",
        "budget_spent",
        "timeline_health",
        "budget_health",
        "safety_health",
        "created_by",
        "completed_by",
        "archived_by",
        "restored_by",
        "archived_at",
        "restored_at",
        "created_at",
        "updated_at",
    ):
        assert key not in project, key

    for url in (
        f"/api/v1/projects/{test_project.id}/inventory",
        f"/api/v1/projects/{test_project.id}/inventory/{uuid.uuid4()}/movements",
        f"/api/v1/projects/{test_project.id}/job-costs",
        f"/api/v1/projects/{test_project.id}/budget",
        f"/api/v1/projects/{test_project.id}/billing-milestones",
        f"/api/v1/projects/{test_project.id}/health",
    ):
        resp = await client.get(url, headers={"Authorization": header})
        assert resp.status_code == 403, url


@pytest.mark.asyncio
async def test_client_mutation_matrix_403(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    """Every relevant mutation endpoint rejects the client role with 403 —
    clients cannot mutate anything even by calling the API directly."""
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    header = await auth_header(client, "client@test.com")
    pid = test_project.id
    cases = [
        ("POST", "/api/v1/projects", {"name": "X", "site_address": "A", "client_name": "C", "start_date": "2026-01-01", "target_end_date": "2026-12-31", "budget_total": 1}),
        ("PATCH", f"/api/v1/projects/{pid}", {"name": "Renamed"}),
        ("POST", f"/api/v1/projects/{pid}/activate", None),
        ("POST", f"/api/v1/projects/{pid}/complete", None),
        ("POST", f"/api/v1/projects/{pid}/archive", None),
        ("POST", f"/api/v1/projects/{pid}/restore", None),
        ("POST", f"/api/v1/projects/{pid}/health-overrides", {"applied_to": "overall", "value": "green", "reason": "test"}),
        ("DELETE", f"/api/v1/projects/{pid}/health-overrides/{uuid.uuid4()}", None),
        ("POST", f"/api/v1/projects/{pid}/inventory", {"name": "Cement", "unit": "bag"}),
        ("PATCH", f"/api/v1/projects/{pid}/inventory/{uuid.uuid4()}", {"name": "X"}),
        ("POST", f"/api/v1/projects/{pid}/inventory/{uuid.uuid4()}/movements", {"movement_type": "received", "quantity": 1}),
        ("POST", f"/api/v1/projects/{pid}/job-costs", {"cost_code": "labor", "description": "d", "amount": 10, "incurred_on": "2026-08-01"}),
        ("POST", f"/api/v1/projects/{pid}/billing-milestones", {"name": "M", "billing_type": "percentage", "billing_percentage": 10}),
        ("POST", f"/api/v1/projects/{pid}/invoices", {"billing_milestone_id": str(uuid.uuid4())}),
        ("POST", f"/api/v1/projects/{pid}/assignments", {"user_id": str(uuid.uuid4())}),
        ("DELETE", f"/api/v1/projects/{pid}/assignments/{uuid.uuid4()}", None),
        ("POST", "/api/v1/users", {"email": "x@example.com", "full_name": "X", "role": "client", "password": "Passw0rd1"}),
        ("PATCH", f"/api/v1/users/{uuid.uuid4()}", {"is_active": False}),
        ("GET", "/api/v1/audit/logs", None),
    ]
    for method, url, body in cases:
        resp = await client.request(method, url, headers={"Authorization": header}, json=body)
        assert resp.status_code == 403, f"{method} {url} -> {resp.status_code}"


@pytest.mark.asyncio
async def test_client_idor_other_project_surfaces(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
):
    """IDOR: a client using another project's UUID on tasks/site-logs/inventory
    must be rejected (403)."""
    admin = await auth_header(client, "admin@test.com")
    other_id = await create_second_project(client, admin)
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)

    header = await auth_header(client, "client@test.com")
    for url in (
        f"/api/v1/projects/{other_id}/tasks",
        f"/api/v1/projects/{other_id}/site-logs",
        f"/api/v1/projects/{other_id}/inventory",
    ):
        resp = await client.get(url, headers={"Authorization": header})
        assert resp.status_code == 403, url


@pytest.mark.asyncio
async def test_google_authenticated_client_parity(
    client: httpx.AsyncClient,
    test_admin_user,
    test_client_user,
    test_db,
    test_project,
    google_jwks,
    monkeypatch,
):
    """A Google-authenticated client gets exactly the same boundary as a
    password client — Google must not grant additional permissions."""
    await assign_user_to_project(test_db, test_project.id, test_client_user.id)
    admin = await auth_header(client, "admin@test.com")
    other_id = await create_second_project(client, admin)
    m = (await create_milestone(client, admin, test_project.id)).json()
    await complete_milestone(client, admin, test_project.id, m["id"])
    inv = (await make_invoice(client, admin, test_project.id, m["id"])).json()
    await client.post(
        f"/api/v1/projects/{test_project.id}/invoices/{inv['id']}/issue",
        headers={"Authorization": admin},
    )

    token = await _google_login_as(client, monkeypatch, google_jwks, "client@test.com")
    g = {"Authorization": f"Bearer {token}"}

    listing = await client.get("/api/v1/projects", headers=g)
    assert listing.status_code == 200
    (item,) = listing.json()
    assert not (set(item.keys()) & CLIENT_FORBIDDEN_KEYS)

    denied = await client.get(f"/api/v1/projects/{other_id}", headers=g)
    assert denied.status_code == 403

    assert (await client.get(f"/api/v1/projects/{test_project.id}/health", headers=g)).status_code == 403
    assert (await client.get(f"/api/v1/projects/{test_project.id}/inventory", headers=g)).status_code == 403

    (invoice,) = (
        await client.get(f"/api/v1/projects/{test_project.id}/invoices", headers=g)
    ).json()
    assert not (set(invoice.keys()) & CLIENT_INVOICE_FORBIDDEN_KEYS)
    assert invoice["amount"] == inv["amount"]

    write = await client.post(
        f"/api/v1/projects/{test_project.id}/tasks",
        headers=g,
        json={"name": "X", "start_date": "2026-01-01", "end_date": "2026-01-02"},
    )
    assert write.status_code == 403

    me = await client.get("/api/v1/auth/me", headers=g)
    assert me.status_code == 200
    assert me.json()["role"] == "client"


@pytest.mark.asyncio
async def test_role_regression_admin_proc_supervisor(
    client: httpx.AsyncClient,
    test_admin_user,
    test_procurement_user,
    test_supervisor_user,
    test_db,
    test_project,
):
    """Admin/procurement keep budgets, supervisors keep the no-money shape and
    health, procurement keeps finance — M6 must not change these roles."""
    admin = await auth_header(client, "admin@test.com")
    proc = await auth_header(client, "procurement@test.com")
    sup = await auth_header(client, "supervisor@test.com")
    await assign_user_to_project(test_db, test_project.id, test_supervisor_user.id)

    admin_p = (
        await client.get(f"/api/v1/projects/{test_project.id}", headers={"Authorization": admin})
    ).json()
    proc_p = (
        await client.get(f"/api/v1/projects/{test_project.id}", headers={"Authorization": proc})
    ).json()
    sup_p = (
        await client.get(f"/api/v1/projects/{test_project.id}", headers={"Authorization": sup})
    ).json()
    assert admin_p["budget_total"] == float(test_project.budget_total)
    assert proc_p["budget_total"] == float(test_project.budget_total)
    assert "budget_total" not in sup_p and "budget_spent" not in sup_p

    sup_health = await client.get(
        f"/api/v1/projects/{test_project.id}/health", headers={"Authorization": sup}
    )
    assert sup_health.status_code == 200  # supervisors keep health (M6)

    proc_jobs = await client.get(
        f"/api/v1/projects/{test_project.id}/job-costs", headers={"Authorization": proc}
    )
    assert proc_jobs.status_code == 200  # procurement finance unchanged
