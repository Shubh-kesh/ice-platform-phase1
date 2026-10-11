# Spark Build Associate — Site Management App
## Simple User Guide (for everyone)

**Admin:** Pankaj | **App link:** https://ice-frontend-uat-386147112888.asia-south1.run.app | **Version:** UAT demo, October 2026

---

## 1. What is this app?

One simple screen to run all your construction sites. Instead of registers,
spreadsheets and phone calls, every site has its own page showing the work
plan, the daily record, the material stock, the money spent, and the bills —
all in one place.

Open the app link above in Chrome or Edge on a computer. This demo version
works best on a desktop or laptop.

---

## 2. How do I log in?

1. Open the app link. You will see the Sign in page.
2. Type your email and password, then click **Sign in**.
3. After login you reach the **Command Center** (your home screen).
4. To log out, click **Sign out** at the bottom of the left menu.

Your demo login (password is the same for all: **DemoPass123**):

| Who is this for | Email | Password | What they do |
|---|---|---|---|
| Admin (Pankaj) | Pankaj1234@gmail.com | DemoPass123 | Everything: sites, team, approvals, money |
| Site Supervisor | kashi.supervisor@example.com | DemoPass123 | Daily logs, work plan updates |
| Procurement | kashi.procurement@example.com | DemoPass123 | Stock, vendors, orders, costs |
| Client | kashi.client@example.com | DemoPass123 | View-only: progress and payment requests |

> Keep your password private. If you cannot log in, contact Pankaj — only an
> admin can reset access.

---

## 3. Your home screen (Command Center)

After login you see cards, one per site — like drawing sheets. Each card shows
the site name, client name, project code (for example PRJ-2026-0001), a status
(Draft, Active, Completed...), a progress bar, and three small colour dots:

| Colour | Meaning |
|---|---|
| Green | On track |
| Yellow (amber) | Needs attention |
| Red | Off track |
| Grey | Not enough data yet |

The three dots stand for **Timeline** (is work on schedule?), **Budget** (is
spending in line with progress?) and **Safety** (grey for now — safety records
come in a later version). Click any card to open that site. The **bell** on the
top right shows your notifications.

---

## 4. What does each person do daily?

**Site Supervisor (your most-used account on site):**

1. Open your site from the Command Center.
2. Go to **DAILY SITE LOGS** and click **New entry**.
3. Fill the date, number of workers present, and weather.
4. Write what was completed today in simple words, for example "Slab casting
   of Block B completed; 18 workers present".
5. If anything is stuck, write it under Issues so it stands out.
6. Click **Save log entry**. Done — one entry per working day.

Then open **TIMELINE** and move the progress slider or status of the tasks
that moved forward today. If a task's dates change, dependent tasks shift
forward automatically and a small notice tells you what moved.

> A saved daily log cannot be edited or deleted later — it is the permanent
> site register. So write carefully before saving.

**Procurement Manager:**

1. Open the site and go to **INVENTORY** to see stock. Items marked **Low
   stock** need ordering.
2. To add stock records, click **Record movement** on an item (Received when
   material comes in, Consumed when used on site).
3. To buy: first add the supplier once under **VENDORS** on the home screen
   (name, phone, payment terms).
4. In the site, open **PURCHASE ORDERS** and click **Create PO**: pick the
   vendor, add each material line (what, how much, price), and create.
5. Click **Submit**. Pankaj (admin) will **Approve** or **Reject** it.
6. When material arrives, open the approved order and click **Receive**: enter
   the delivery note number, the quantity received per line, and **Verify &
   receive**. This one step adds the stock AND records the cost — no double
   entry.
7. Record other spending under **JOB COST** with the right trade (Masonry,
   Electrical, Plumbing...) so the budget figures stay correct.

**Client (view-only):**

1. Log in and open your site. You see the work plan (**TIMELINE**) and
   **DAILY SITE LOGS** — what happened each day.
2. Open **PAYMENT REQUESTS** to see your bills: number, milestone, amount, due
   date. Overdue bills show in red.
3. You cannot change anything, and you never see internal budgets or stock —
   by design.

**Admin (Pankaj):**

- **New site:** Command Center → **New site** → fill name, client, address,
  dates, budget → **Create project**. It starts as Draft; use **Activate** on
  the site page to start it, **Mark complete** / **Archive** later.
- **Team:** **TEAM / USERS** on the home screen — add people, set their role,
  assign them to sites, or deactivate accounts.
- **Approvals:** approve or reject purchase orders (rejection needs a reason),
  issue invoices, mark them paid or cancel.
- **Money setup:** add billing milestones (for example "Slab casting — 10% of
  contract"), **Complete** them when done, then **Generate invoice**. Amounts
  are calculated automatically — nobody types them.

---

## 5. The bell and the assistant

**Bell (top right):** tells you automatically about schedule shifts, new
payment requests, low stock, new site assignments, and order approvals. Click
an item to jump to that screen. There are no email or SMS alerts in this
version — the bell is the only channel, so glance at it daily.

**ICE Copilot (left menu):** a helper you can ask in plain words, for example
"Which projects need attention?" or "Show inventory for Kashi Kunj". It only
answers from data you are allowed to see. It cannot change anything by
itself — if it ever proposes an action, you must approve it first.

---

## 6. Good habits (keeps everyone's numbers trustworthy)

- Write the daily log **every working day**, the same day — not from memory
  a week later.
- Record stock movements and costs **as they happen**; missing entries are
  invisible errors.
- Receive purchase orders **through the Receive button only** — that is what
  keeps stock and costs in sync.
- Check the bell every morning.
- For anything account-related (new user, role change, login problem), ask
  Pankaj instead of sharing passwords.

---

## 7. What this version cannot do yet (so you don't go looking)

- No photo upload or voice notes in daily logs yet (text only).
- No phone app and no offline mode — needs internet on a computer.
- Left-menu items **Inventory**, **Finance**, **Quality & Safety** are greyed
  out placeholders; those features already live inside each site page.
- Safety dot stays grey until safety records are added in a later version.
- No email/SMS alerts, no export to accounting software yet.

---

## 8. Need help?

Contact **Pankaj (Admin, Spark Build Associate)** for logins, access, new
sites, approvals, or anything in this guide that doesn't match what you see
on screen — the screen is always the latest truth.

*Happy building!*
