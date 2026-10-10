# Kashi Kunj — Presentation Notes (Speaker Script)

These notes accompany `KASHI_KUNJ_STAKEHOLDER_PRESENTATION.pptx` / `.md`.
Keep them **nontechnical** — the audience is business and site people, not
engineers. All demo figures are fictional.

---

## Slide 1 — Title
> "Good morning. We are Sparkbuild, and this is how we will run our projects —
> every schedule, every site, every rupee and every conversation, in one place.
> Everything I'm about to show is live, on a real project called **Kashi Kunj**
> here in Jabalpur."

## Slide 2 — The way construction usually works
> "Be honest with yourselves: how much of today's project status lives in
> spreadsheets and in people's heads? How often do you discover a material
> shortage on the morning it's needed? That's the world we all know."
- Pause. Let them nod. Keep it short — don't lecture your own audience.

## Slide 3 — The way it should work
> "So we set one rule for ourselves: **one screen, one truth, alerts before
> problems.** This is the platform that does that. Today I'll show it on one
> project — but the same screen manages every project we run."
- Key phrase to land: *one source of truth.*

## Slide 4 — Meet Kashi Kunj
> "This is the project we'll walk through — a residential building, 47% done,
> ₹90 lakh budget, 16 tasks, 8 daily site logs, 5 suppliers, and four of the
> roles that will use this system every day: the owner, the site supervisor,
> procurement, and the client."
- Establish the cast now; you'll switch between them live.

## Slide 5 — One screen, every project
> "Open the Command Center: every project, with a health light. Kashi Kunj is
> **amber** today. Why? The system says it plainly: we are 47% complete against
> 52% of the schedule. Nobody painted this colour — the data did."
- Live: point at the amber card, read the reason out loud.

## Slide 6 — A schedule that thinks
> "Sixteen linked tasks, like the real plan. Notice **Internal Plaster** — it
> was planned too early. The system caught the conflict, shifted it, and sent
> the team an alert. And two tasks are overdue right now, so everyone knows
> where to focus tomorrow morning."
- Live: open the Gantt, hover the shifted task, open the notification bell.

## Slide 7 — Every day on site, captured
> "The supervisor's daily log: what was done, weather, headcount, issues. See
> this note from a few days ago — *'Cement stock running low.'* A small
> complaint that the system turns into an actual alert."

## Slide 8 — Materials without surprises
> "Ten material lines with live balances. **Cement is at 25 bags — below its
> reorder level of 30 — and the system raised the alarm by itself.** Every bag
> sits on a ledger that cannot be edited: received, used, remaining. What the
> screen says is what the store really holds."
- Live: open cement, show the ledger, then optionally receive the outstanding
  120 bags and watch the alert clear.

## Slide 9 — Buying with controls
> "Purchases run a real workflow. Today we have five orders in five states:
> one fully received, one half-received, one approved and waiting on delivery,
> **one sitting on the owner's desk for approval**, and one that was rejected —
> because the rate was too high, and that reason is recorded for everyone to
> see. Approvals belong to the owner alone."
- Live: approve the pending PO (as admin) or show procurement is blocked from
  approving.

## Slide 10 — Money you can trust
> "Budget ₹90 lakh; spent ₹32.98 lakh; remaining ₹57 lakh. That spent figure is
> not typed by anyone — it's the sum of the cost ledger, every rupee traceable
> to a labour line, a material line, or a supplier receipt."
- The phrase to land: *no hand-typed totals.*

## Slide 11 — Client confidence
> "The client sees a clean portal: progress, schedule, and their invoices. Two
> paid, one outstanding. They never see our internal costs or suppliers — and
> the system enforces that, not a promise."

## Slide 12 — The right view for the right role
> "Owner: everything. Supervisor: the site, no money. Procurement: suppliers,
> orders, stock. Client: progress and invoices. Access is enforced by the
> system — the wrong role is refused, instantly and every time."
- If you have a second screen, log in as the client and as the supervisor to
  show the difference live.

## Slide 13 — AI that helps — with guardrails
> "Ask in plain words: *'What is low in stock?'* — it answers. But when the
> assistant wants to *change* something, it must ask a human first. Watch: I'll
> ask it to create a task… it proposes… and I'll reject it, so the project
> stays exactly as it is."
- Live: run the HITL prompt, show the approval request, press reject.
- If the AI is slow or offline: *"Live model — it's a bit shy today,"* and move
  on; the rest of the demo does not depend on it.

## Slide 14 — The proof is in the trail
> "Every change is audited — who, what, when. Every alert you saw was raised by
> the system, not typed in. And this whole dataset can be reset and re-run
> identically: we rehearsed it this morning, and we can rebuild it for you
> tomorrow."

## Slide 15 — Close
> "You saw the full cycle on one project. The same Command Center runs every
> Sparkbuild site. We'd like to run a pilot on your live projects. Thank you —
> questions?"

---

## Logistics checklist
- Seeded DB + `verify` = **DEMO READY (42 checks passed)** before the room
  enters.
- Tabs ready: Admin dashboard, supervisor, procurement, client, Copilot.
- If you run the live cement-receipt or PO-approval actions, run `reseed`
  afterwards so the deck is pristine for the next meeting.
- Demo password `Kashi@Demo26`; note it on the presenter's card.
- Backup plan if Copilot is unavailable: skip Slide 13's live part and keep the
  rest of the flow intact.