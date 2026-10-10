# Kashi Kunj — Client Demo Runbook

Step-by-step script for the **4-role client meeting** (Owner, Site Supervisor,
Procurement Manager, Client), built on the seeded demo project. Assumes the
frontend is running against the local backend and the seed has been applied.

> Prep: run the seed, run `verify`, and re-run `seed` once more to make it
> idempotent (see §7). All demo logins use password **`Kashi@Demo26`**.
> All names/figures are fictional demo data.

---

## 1. Before the client arrives (5 min)

```bash
cd backend
docker compose up -d postgres backend          # backend auto-runs alembic head
# one-time seed (export the demo password):
docker compose exec -T -e ICE_KASHI_DEMO=true -e ICE_KASHI_DEMO_PASSWORD='Kashi@Demo26' \
  backend python -m app.demo.kashi_kunj seed
docker compose exec -T -e ICE_KASHI_DEMO_PASSWORD='Kashi@Demo26' \
  backend python -m app.demo.kashi_kunj verify
```

`verify` must end with **DEMO READY (42 checks passed)**. If it does not,
re-run `seed` (it is idempotent) and `verify` again. Then start the frontend
(`cd frontend && npm run dev`) and open http://localhost:5173.

> **Warm-up reset** (optional, to guarantee a pristine deck): use `reseed`
> instead of `seed` — it removes and recreates the Kashi data in one step.

## 2. Open (2 min) — Admin dashboard

- Sign in as **Kashi Admin** (`kashi.admin@example.com`).
- Show the **Command Center**: project cards with health colours, the single
  active project, and the summary tiles.
- Open **Kashi Kunj** → the project dashboard: **47% complete**, **overall
  health AMBER**, timeline AMBER, budget GREEN. Read the health reasons aloud
  (they are computed from data: SPI 0.91, 2 overdue tasks, spend vs progress).
- Frame: *"This is not a colour the team picked — the system derives it from
  the schedule and the cost ledger every time you open the page."*

## 3. Timeline & work tracking (3 min)

- Open the **Timeline/Gantt** for Kashi Kunj: 16 tasks with dependencies.
- Point at **Internal Plaster**: it was planned before its predecessor
  finished; the system **shifted it automatically** and told the team. Show the
  notification bell (schedule-shift alert) as the proof.
- Open **Daily Site Logs**: 8 dated entries with work summaries and issues —
  including the note *"Cement stock running low at site"* that connects to the
  inventory story.
- Switch to **Site Supervisor** (`kashi.supervisor@example.com`, Arun Sharma):
  same tasks and logs, **no budget/money figures anywhere** — supervisors are
  never given internal financials.

## 4. Procurement — purchase orders (4 min)

- Switch to **Procurement Manager** (`kashi.procurement@example.com`,
  Vikram Rao). Open **Purchase Orders** for Kashi Kunj.
- Walk the 5 states: **received** (steel, full receipt `MKS-2031`),
  **partially received** (cement — 180 of 300 bags in), **approved**
  (electrical/plumbing), **pending approval** (AAC + tile adhesive),
  **rejected** (waterproofing — read the rejection reason aloud).
- **Live action 1**: approve the pending PO → watch the status flip and the
  approval notification appear.
- **Live action 2**: receive the remaining **120 bags of cement** against the
  cement PO → stock rises from 25 to 145 bags, cost ledger updates, the
  low-stock alert clears.
- Show that procurement **cannot** approve a PO (button is disabled / 403) —
  approvals are admin-only. Switch to **Kashi Admin** to do it if needed.

## 5. Inventory & finance (4 min)

- **Inventory**: 10 items; **Cement (OPC 53) is the only LOW-STOCK item**
  (25 of 30 bags threshold). Open the item → the **stock-movement ledger**
  shows every receipt and consumption; the report proves on-hand equals the
  ledger balance.
- **Finance** (admin): **Budget roll-up** — ₹90,00,000 total, ₹32,98,150
  spent, ₹57,01,850 remaining, per-cost-code split. Emphasise that `spent`
  comes from the job-cost ledger (manual costs + PO receipts), never a
  hand-typed number.
- **Invoicing**: the 6-milestone schedule of values and 3 invoices —
  **2 paid** (₹9L mobilisation, ₹13.5L foundation), **1 sent** (₹22.5L RCC
  structure).

## 6. Client portal & Copilot (4 min)

- Switch to **Client** (`kashi.client@example.com`, Ananya Gupta): the portal
  shows the project, progress, and **only issued invoices** (no internal
  budget, no POs, no inventory, no cost codes — 403s if probed).
- **Copilot** (Assistant): ask *"Tell me about Kashi Kunj"*,
  *"What is low in stock?"*, *"Show open purchase orders"*.
- **Live action 3 (HITL)**: ask Copilot *"Create a task for Kashi Kunj called
  Client meeting follow-up"* → it proposes the action and requires approval →
  **reject it** so the deck stays pristine. This shows AI *with* guardrails.

## 7. After the meeting

To restore a pristine deck for the next rehearsal/meeting:

```bash
docker compose exec -T -e ICE_KASHI_DEMO=true -e ICE_KASHI_DEMO_PASSWORD='Kashi@Demo26' \
  backend python -m app.demo.kashi_kunj reseed
docker compose exec -T -e ICE_KASHI_DEMO_PASSWORD='Kashi@Demo26' \
  backend python -m app.demo.kashi_kunj verify
```

`reset` alone removes Kashi data (4 users, the project and everything hanging
off it, the 5 demo vendors) and leaves all unrelated data untouched.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `verify` shows a FAIL | re-run `seed` (idempotent) then `verify` again |
| Login fails with demo password | the users already exist with a different password — `reseed` and use `Kashi@Demo26` |
| Copilot answers are slow / error | LLM quota exhausted; the demo works without it — skip §6 Copilot |
| Frontend shows no project | confirm the seed ran against the same DB the backend container uses (it does by default) |
| Health shows GREEN overall | a fresh seed shifted dates; re-run `verify` — the AMBER state is produced by the designed schedule |