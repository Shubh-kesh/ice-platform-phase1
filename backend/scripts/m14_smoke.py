"""M14 live HTTP smoke test (Render/dev-style) — drives a real uvicorn server
over HTTP through the full vendor + PO workflow per the plan §27.

Not a pytest file. Run from backend/ after `python scripts/m14_smoke_prep.py`.
"""
import os

import httpx

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8011/api/v1")


def login(client, email, password="TestPass123"):
    r = client.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def step(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    return ok


def main():
    checks = []
    with httpx.Client(timeout=30) as client:
        admin = login(client, "admin@test.com")
        proc = login(client, "procurement@test.com")
        sup = login(client, "supervisor@test.com")
        cli = login(client, "client@test.com")

        # --- Vendors (procurement creates) ---
        r = client.post(f"{BASE}/vendors", headers=proc, json={"name": "Smoke Cement Co", "payment_terms": "NET 30"})
        checks.append(step("vendor create (procurement) -> 201", r.status_code == 201, r.text))
        vendor = r.json()
        checks.append(step("vendor is_active default true", vendor["is_active"] is True))

        dup = client.post(f"{BASE}/vendors", headers=proc, json={"name": "Smoke Cement Co"})
        checks.append(step("duplicate vendor -> 409", dup.status_code == 409, dup.text))

        deact = client.patch(f"{BASE}/vendors/{vendor['id']}", headers=proc, json={"is_active": False})
        checks.append(step("vendor soft-deactivate -> is_active false", deact.status_code == 200 and deact.json()["is_active"] is False, deact.text))
        react = client.patch(f"{BASE}/vendors/{vendor['id']}", headers=proc, json={"is_active": True})
        checks.append(step("vendor reactivate", react.status_code == 200 and react.json()["is_active"] is True, react.text))

        # --- Supervisor/client cannot see vendors ---
        checks.append(step("supervisor vendor list -> 403", client.get(f"{BASE}/vendors", headers=sup).status_code == 403))
        checks.append(step("client vendor list -> 403", client.get(f"{BASE}/vendors", headers=cli).status_code == 403))

        # --- Projects (need one from seed? test DB has no projects) ---
        r = client.get(f"{BASE}/projects", headers=admin)
        checks.append(step("admin project list", r.status_code == 200, r.text))
        projects = r.json()
        if not projects:
            r = client.post(f"{BASE}/projects", headers=admin, json={
                "name": "Smoke Residence", "site_address": "1 Smoke Rd", "client_name": "Smoke Co",
                "start_date": "2026-01-01", "target_end_date": "2026-12-31", "budget_total": 1000000,
            })
            checks.append(step("project create", r.status_code == 201, r.text))
            projects = r.json() if isinstance(r.json(), list) else [r.json()]
        project = projects[0] if isinstance(projects, list) else projects
        project_id = project["id"]
        project_code = project["project_code"]

        # --- PO lifecycle ---
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders", headers=proc, json={
            "vendor_id": vendor["id"], "tax_rate": 18,
            "lines": [
                {"description": "Cement", "quantity": 100, "unit": "bag", "unit_price": 350, "cost_code": "material"},
                {"description": "Steel", "quantity": 10, "unit": "t", "unit_price": 1000, "cost_code": "structure"},
            ],
        })
        checks.append(step("PO create (procurement, nested lines + tax) -> 201", r.status_code == 201, r.text))
        po = r.json()
        checks.append(step(f"po_number format PO-{project_code}-0001", po["po_number"] == f"PO-{project_code}-0001", po["po_number"]))
        checks.append(step("total = sum(lines) + tax", po["total_amount"] == 53100.0, str(po["total_amount"])))  # (35000 + 10000) + 18%
        checks.append(step("PO starts DRAFT", po["status"] == "draft", po["status"]))

        # supervisor/client 403 on POs
        checks.append(step("supervisor PO list -> 403", client.get(f"{BASE}/projects/{project_id}/purchase-orders", headers=sup).status_code == 403))
        checks.append(step("client PO list -> 403", client.get(f"{BASE}/projects/{project_id}/purchase-orders", headers=cli).status_code == 403))

        # submit -> admins notified
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders/{po['id']}/submit", headers=proc)
        checks.append(step("PO submit (procurement) -> pending_approval", r.status_code == 200 and r.json()["status"] == "pending_approval", r.text))
        n = client.get(f"{BASE}/notifications", headers=admin).json()
        checks.append(step("admin got po_submitted", any(x["type"] == "po_submitted" for x in n)))

        # procurement cannot approve
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders/{po['id']}/approve", headers=proc)
        checks.append(step("procurement approve -> 403", r.status_code == 403, r.text))

        # admin approves -> creator + admin notified
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders/{po['id']}/approve", headers=admin)
        checks.append(step("admin approve -> approved", r.status_code == 200 and r.json()["status"] == "approved", r.text))
        n = client.get(f"{BASE}/notifications", headers=proc).json()
        checks.append(step("creator (procurement) got po_approved", any(x["type"] == "po_approved" for x in n)))

        # procurement cannot cancel APPROVED (checked before admin cancels it)
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders/{po['id']}/cancel", headers=proc)
        checks.append(step("procurement cancel APPROVED -> 403", r.status_code == 403, r.text))

        # admin cancels APPROVED
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders/{po['id']}/cancel", headers=admin)
        checks.append(step("admin cancel APPROVED -> cancelled", r.status_code == 200 and r.json()["status"] == "cancelled", r.text))

        # reject -> revise -> edit -> submit cycle on a second PO
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders", headers=proc, json={
            "vendor_id": vendor["id"], "lines": [{"description": "Pipes", "quantity": 4, "unit": "pcs", "unit_price": 500, "cost_code": "plumbing"}],
        })
        po2 = r.json()
        client.post(f"{BASE}/projects/{project_id}/purchase-orders/{po2['id']}/submit", headers=proc)
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders/{po2['id']}/reject", headers=admin, json={"rejected_reason": "reprice"})
        checks.append(step("reject -> rejected (reason)", r.status_code == 200 and r.json()["status"] == "rejected", r.text))
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders/{po2['id']}/revise", headers=proc)
        checks.append(step("revise -> draft", r.status_code == 200 and r.json()["status"] == "draft", r.text))
        line = r.json()["lines"][0]
        client.patch(f"{BASE}/projects/{project_id}/purchase-orders/{po2['id']}/lines/{line['id']}", headers=proc, json={"unit_price": 400})
        r = client.get(f"{BASE}/projects/{project_id}/purchase-orders/{po2['id']}", headers=admin)
        checks.append(step("line edit recomputed total", r.json()["total_amount"] == 1600.0, str(r.json()["total_amount"])))

        # idempotency replay
        key = "smoke-key-0001"
        body = {"vendor_id": vendor["id"], "lines": [{"description": "Bricks", "quantity": 100, "unit": "pcs", "unit_price": 5, "cost_code": "masonry"}]}
        r1 = client.post(f"{BASE}/projects/{project_id}/purchase-orders", headers={**proc, "Idempotency-Key": key}, json=body)
        r2 = client.post(f"{BASE}/projects/{project_id}/purchase-orders", headers={**proc, "Idempotency-Key": key}, json=body)
        checks.append(step("idempotent PO create replay (same id)", r1.status_code == 201 and r2.status_code == 201 and r1.json()["id"] == r2.json()["id"], r2.text))

        # archive -> read-only
        client.post(f"{BASE}/projects/{project_id}/archive", headers=admin)
        r = client.post(f"{BASE}/projects/{project_id}/purchase-orders", headers=admin, json={
            "vendor_id": vendor["id"], "lines": [{"description": "Late", "quantity": 1, "unit": "pcs", "unit_price": 1, "cost_code": "other"}],
        })
        checks.append(step("archive: PO create -> 403", r.status_code == 403, r.text))
        r = client.get(f"{BASE}/projects/{project_id}/purchase-orders", headers=admin)
        checks.append(step("archive: PO list still readable (A/P)", r.status_code == 200, r.text))

    failed = [c for c in checks if not c]
    print(f"\nSMOKE RESULT: {len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
